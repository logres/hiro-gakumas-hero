"""状态推算与识别互验的主循环部分（docs/state-events.md §5，契约 1.2）。

    apply_event(state, event)   事件记进 ledger，按事件改牌组，调用预测器 hiro.state.events.predict 得到预测
    check(state, obs, preds)    观测到来时：先过不变量，再和到期预测比 → Check 列表
    gate(obs, checks)           read_error 的读数从观测里去掉（不进状态、不进决策），返回干净的观测
    events_from_step(...)       由已执行的决策推出事件（action 事件）；取代 hiro.loop.ledger 的记账（同一套账）

reduce 本身仍是纯函数；Session.observe 依次调用 check → gate → reduce → mark。
"""

from __future__ import annotations

import copy
from collections import Counter
from typing import Any

from hiro.contracts import Check, Event, Expect, GameState, Observation, Prediction, Source

LEDGER_KEEP = 200  # GameState.ledger 只留最近 N 条，完整的在 trace

# 观测字段（按页面 section）→ 字段路径
SECTION = {"ACTION_SELECT": "produce", "DECK_LIST": "produce", "HIF_EXAM": "exam"}


def _no_prediction(state, event) -> list:
    return []


# ---------------------------------------------------------------------------- 事件
def apply_event(state: GameState, event: Event, *, predictor=None) -> tuple[GameState, list[Prediction]]:
    """纯函数：返回新状态与预测。牌组按事件增减（已知时）；字段状态记 predicted。"""
    s = copy.deepcopy(state)
    s.ledger.append(event)
    del s.ledger[:-LEDGER_KEEP]
    _apply_deck(s, event)
    if predictor is None:
        try:  # 游戏专用的预测器（hiro.state.events）不在开源版里：没有就不做预测
            from hiro.state.events import predict as predictor
        except ImportError:
            predictor = _no_prediction
    try:
        raw = predictor(state, event.to_dict())  # 预测基于事件之前的状态
    except Exception as e:  # 预测器异常不能影响主循环
        s.conflicts.append(f"seq {event.seq}: 预测 {event.kind} 失败：{type(e).__name__}: {e}")
        raw = []
    preds = [_prediction(p) for p in raw]
    for p in preds:
        for path in p.fields:
            if s.field_status.get(path) != "pending":
                s.field_status[path] = "predicted"
    return s, preds


def _prediction(p: Any) -> Prediction:
    if isinstance(p, Prediction):
        return p
    fields = {k: (v if isinstance(v, Expect) else Expect(**{kk: vv for kk, vv in v.items() if kk in Expect.__dataclass_fields__}))
              for k, v in (p.get("fields") or {}).items()}  # fmt: skip
    return Prediction(seq=p.get("seq", 0), event_seq=p.get("event_seq", 0), fields=fields, due=p.get("due", "any"),
                      expires_after=p.get("expires_after"))  # fmt: skip


def _apply_deck(s: GameState, e: Event) -> None:
    if e.kind == "DECK_REVIEW" and e.args.get("deck") is not None:
        s.produce = s.produce if s.produce is not None else {}
        s.produce.setdefault("deck", [])
    prod = s.produce if s.produce is not None else None
    if prod is None or prod.get("deck") is None:
        return
    deck: list = prod["deck"]
    a = e.args
    before_len = len(deck)
    full = (s.field_status.get("produce.deck") in ("verified", "predicted")
            and isinstance(prod.get("deck_size"), int) and prod["deck_size"] == len(deck))
    changed = False

    def pending_deck():
        if "produce.deck" not in s.pending_review:
            s.pending_review.append("produce.deck")
        s.field_status["produce.deck"] = "pending"

    def add(card_id, upgrade=0):
        nonlocal changed
        if card_id:
            deck.append({"card_id": card_id, "upgrade": int(upgrade or 0)})
            changed = True

    def remove(card_id, upgrade=None):
        nonlocal changed
        i = next((i for i, c in enumerate(deck) if c.get("card_id") == card_id
                  and (upgrade is None or c.get("upgrade") == upgrade)), None)
        if i is not None:
            deck.pop(i)
            changed = True
            return True
        elif card_id:
            s.pending_review.append("produce.deck") if "produce.deck" not in s.pending_review else None
        return False

    if e.kind in ("CARD_ACQUIRE", "SHOP_BUY") and a.get("card_id"):
        add(a["card_id"], a.get("upgrade"))
    elif e.kind == "CARD_DELETE":
        remove(a.get("card_id"), a.get("upgrade"))
    elif e.kind == "CARD_CHANGE":
        if remove(a.get("remove_card_id"), a.get("remove_upgrade")):
            add(a.get("card_id"), a.get("upgrade"))
    elif e.kind == "CARD_UPGRADE":
        target = a.get("upgrade")
        matches = [c for c in deck if a.get("card_id") and c.get("card_id") == a["card_id"]
                   and type(target) is int and target > 0 and type(c.get("upgrade")) is int
                   and c["upgrade"] == target - 1]
        if len(matches) == 1:
            matches[0]["upgrade"] = target
            s.sources["produce.deck"] = Source("event", e.seq)
        else:
            # Count is unchanged, but neither a duplicate nor an absent version
            # establishes which owned copy was upgraded.
            pending_deck()
    elif e.kind == "CARD_CUSTOMIZE":
        matches = [c for c in deck if a.get("card_id") and c.get("card_id") == a["card_id"]
                   and (a.get("upgrade") is None or c.get("upgrade") == a["upgrade"])]
        if len(matches) == 1:
            matches[0]["customized"] = True
            matches[0]["customization_effects_known"] = False
        # An identity and upgrade do not describe the newly customized effect.
        # Keep the count proof, and require a fresh inventory/effect observation.
        pending_deck()
    elif e.kind == "DECK_REVIEW" and a.get("deck") is not None:
        prod["deck"] = [{"card_id": c.get("card_id"), "upgrade": c.get("upgrade"),
                         **({"customized": c["customized"]} if "customized" in c else {})}
                        for c in a["deck"]]
        s.pending_review = [f for f in s.pending_review if f != "produce.deck"]
        complete = (e.confirmed is True and a.get("deck_size", len(prod["deck"])) == len(prod["deck"])
                    and all(c.get("card_id") and type(c.get("upgrade")) is int and c["upgrade"] >= 0
                            for c in prod["deck"]))
        prod["deck_size"] = len(prod["deck"]) if complete else None
        s.field_status["produce.deck"] = "verified" if complete else "pending"
        s.field_status["produce.deck_size"] = "verified" if complete else "pending"
        if complete:
            s.sources["produce.deck"] = Source("review", e.seq)
            s.sources["produce.deck_size"] = Source("review", e.seq)
        else:
            pending_deck()
    elif e.kind in ("CARD_AUTO_PROCESS", "UNMODELED_CHANGE") and "deck" in str(a.get("field", "deck")):
        if "produce.deck" not in s.pending_review:
            s.pending_review.append("produce.deck")
        s.field_status["produce.deck"] = "pending"
        s.field_status["produce.deck_size"] = "pending"
        prod["deck_size"] = None
    card_event = e.kind in ("CARD_ACQUIRE", "SHOP_BUY", "CARD_DELETE", "CARD_CHANGE") and (e.kind != "SHOP_BUY" or a.get("card_id"))
    if card_event:
        complete_change = e.kind != "CARD_CHANGE" or bool(a.get("remove_card_id") and a.get("card_id") and len(deck) == before_len)
        if (changed and complete_change and full
                and (e.confirmed is True or (e.origin == "action" and e.ref.get("decision_seq") is not None))):
            prod["deck_size"] = len(deck)
            s.sources["produce.deck"] = Source("event", e.seq)
            s.sources["produce.deck_size"] = Source("event", e.seq)
            status = "verified" if e.confirmed is True else "predicted"
            s.field_status["produce.deck"] = status
            s.field_status["produce.deck_size"] = status
        else:
            prod["deck_size"] = None
            s.field_status["produce.deck"] = "pending"
            s.field_status["produce.deck_size"] = "pending"


def confirmed_deck_size(steps, final_deck: list | None) -> int | None:
    """Recover a count only from a complete review followed by recorded card events.

    This proves inventory cardinality only, not card upgrades, customization or
    current effect text. Callers must not mark the full deck verified from this
    result. Action events must come from a successful execution. An observed event
    paired with that action is the same acquisition and contributes no second delta.
    """
    owned = None
    pending: Counter = Counter()
    for step in steps:
        if step.get("_segment_start"):
            if pending:
                owned = None  # 确认弹窗不能跨 trace 段靠重复的 seq 猜配对
                pending.clear()
            continue
        for event in step.get("events") or []:
            kind, args = event.get("kind"), event.get("args") or {}
            if kind == "DECK_REVIEW":
                deck = args.get("deck")
                owned = (Counter(card["card_id"] for card in deck)
                         if event.get("confirmed") is True and isinstance(deck, list)
                         and args.get("deck_size", len(deck)) == len(deck)
                         and all(isinstance(card, dict) and card.get("card_id") for card in deck) else None)
                pending.clear()
                continue
            if kind in ("CARD_AUTO_PROCESS", "UNMODELED_CHANGE") and "deck" in str(args.get("field", "deck")):
                owned = None
                pending.clear()
                continue
            if kind not in ("CARD_ACQUIRE", "SHOP_BUY", "CARD_DELETE", "CARD_CHANGE") or owned is None:
                continue
            if kind == "SHOP_BUY" and not args.get("card_id"):
                continue
            key = _pair_key(to_event(event))
            paired_seq = (event.get("ref") or {}).get("paired")
            if event.get("origin") == "observed" and paired_seq is not None:
                pair = (paired_seq, key)
                if event.get("confirmed") is not True or pending[pair] <= 0:
                    owned = None
                    pending.clear()
                else:
                    pending[pair] -= 1
                    if pending[pair] == 0:
                        del pending[pair]
                continue
            action = event.get("origin") == "action"
            trusted = (event.get("confirmed") is True or (action and (step.get("execution") or {}).get("ok") is True
                       and (event.get("ref") or {}).get("decision_seq") is not None))
            card_id = args.get("card_id")
            old_id = args.get("remove_card_id") if kind == "CARD_CHANGE" else card_id
            if not trusted or not card_id and kind != "CARD_DELETE" or not old_id and kind in ("CARD_DELETE", "CARD_CHANGE"):
                owned = None
                pending.clear()
            elif kind in ("CARD_ACQUIRE", "SHOP_BUY"):
                owned[card_id] += 1
            elif owned[old_id] <= 0:
                owned = None
                pending.clear()
            else:
                owned[old_id] -= 1
                if kind == "CARD_CHANGE":
                    owned[card_id] += 1
            if owned is not None and action and event.get("confirmed") is not True:
                pending[(event.get("seq"), key)] += 1
    final = (Counter(card.get("card_id") for card in final_deck)
             if isinstance(final_deck, list) and all(isinstance(card, dict) and card.get("card_id") for card in final_deck) else None)
    return sum(final.values()) if owned is not None and not pending and final is not None and +owned == final else None


def events_from_step(page: str | None, action: dict, ok: bool, page_fields: dict, produce: dict | None, *, seq: int) -> list[Event]:
    """已执行成功的决策 → action 事件（hiro.loop.ledger 的规则，改为产出事件）。"""
    if not ok or not action:
        return []
    kind, args = action.get("kind"), action.get("args") or {}
    ev: list[Event] = []

    def E(k, **a):
        ev.append(Event(seq=seq, kind=k, origin="action", args={kk: vv for kk, vv in a.items() if vv is not None}, basis="observe_only",
                        ref={"decision_seq": seq}))  # fmt: skip

    if page == "SELECT_CARD" and kind == "ActivateEffect":
        cands = page_fields.get("candidates") or []
        for i in args.get("pick_indexes") or []:
            if 0 <= int(i) < len(cands):
                E("CARD_ACQUIRE", card_id=cands[int(i)].get("card_id"), upgrade=cands[int(i)].get("upgrade"))
    elif page == "SELECT_CARD" and kind == "Reroll":
        E("CARD_REROLL")
    elif page == "SELECT_CARD" and kind == "ExcludeCard":
        cands = page_fields.get("candidates") or []
        i = args.get("pick_index")
        E("CARD_EXCLUDE", card_id=cands[i].get("card_id") if isinstance(i, int) and 0 <= i < len(cands) else None)
    elif page == "CONSULT" and kind == "ShopBuy":
        if args.get("service") == "delete":
            deck = (produce or {}).get("deck") or []
            i = args.get("card_index")
            c = deck[i] if isinstance(i, int) and 0 <= i < len(deck) else {}
            E("CARD_DELETE", card_id=c.get("card_id"), upgrade=c.get("upgrade"), source="consult")
        elif "index" in args:
            shelf = page_fields.get("shelf") or []
            i = int(args["index"])
            item = shelf[i] if 0 <= i < len(shelf) else {}
            E("SHOP_BUY", kind="card" if item.get("card_id") else "drink", card_id=item.get("card_id"), drink_id=item.get("drink_id"),
              upgrade=item.get("upgrade"), price=item.get("price"))  # fmt: skip
    elif page == "SKILL_CARD_CHANGE_2" and kind == "ChangeCard" and not args.get("cancel") and args.get("remove_card_id"):
        E("CARD_CHANGE", remove_card_id=args["remove_card_id"], remove_upgrade=args.get("remove_upgrade"),
          card_id=args.get("card_id"), upgrade=args.get("upgrade"))
    elif page == "SKILL_CARD_REMOVAL" and args.get("card_id"):
        E("CARD_DELETE", card_id=args["card_id"], upgrade=args.get("upgrade"), source="event")
    elif page == "SKILL_CARD_ENHANCE" and kind == "EnhanceCard" and args.get("card_id") and not args.get("cancel"):
        # EnhanceCard identifies the owned source version; result observations
        # already describe the target version. Normalize before ledger replay.
        source_upgrade = args.get("upgrade")
        known = type(source_upgrade) is int and source_upgrade >= 0
        E("CARD_UPGRADE", card_id=args["card_id"], upgrade=source_upgrade + 1 if known else None,
          from_upgrade=source_upgrade if known else None, source="event")
    elif (page == "SPECIAL_GUIDANCE" and kind == "CustomizeCard" and args.get("menu_session") is True
          and args.get("strict") is True and args.get("card_id")
          and type(args.get("upgrade")) is int and args["upgrade"] >= 0
          and type(args.get("levels")) is int and args["levels"] == 1):
        E("CARD_CUSTOMIZE", card_id=args["card_id"], upgrade=args["upgrade"],
          customize_id=args.get("customize_id"), item_index=args.get("item_index"),
          price=args.get("price"), source="observed_menu_execution")
    elif page == "PDRINK_MAX" and kind == "DiscardDrink" and args.get("receive") and args.get("discard"):
        E("DRINK_DISCARD", index=args["discard"][0])
    return ev


# ---------------------------------------------------------------------------- 互验
def _flat(obs: Observation) -> dict[str, Any]:
    section = SECTION.get(obs.page.name)
    if section is None:
        return {}
    out: dict[str, Any] = {}
    for k, v in obs.fields.items():
        if isinstance(v, dict) and k in ("params",):
            for kk, vv in v.items():
                out[f"{section}.{k}.{kk}"] = vv
        else:
            out[f"{section}.{k}"] = v
    return out


def _get(state: GameState, path: str):
    cur: Any = state
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else getattr(cur, part, None)
        if cur is None:
            return None
    return cur


def builtin_invariants(state: GameState, obs: Observation) -> list[Check]:
    """§4 的最小集合（数据确认交付 hiro.state.invariants 后由它取代）：param_monotonic、score_monotonic、digit_count。"""
    out: list[Check] = []
    flat = _flat(obs)
    for path, v in flat.items():
        if not isinstance(v, (int, float)):
            continue
        old = _get(state, path)
        if not isinstance(old, (int, float)):
            continue
        if path.startswith("produce.params.") and v < old:
            out.append(Check(seq=obs.seq, field=path, predicted={"min": old}, observed=v, verdict="read_error", rule="param_monotonic",
                             action="discard_reread"))  # fmt: skip
        elif path == "exam.score" and v < old:
            out.append(Check(seq=obs.seq, field=path, predicted={"min": old}, observed=v, verdict="read_error", rule="score_monotonic",
                             action="discard_reread"))  # fmt: skip
        elif path in ("produce.produce_point", "produce.star") and old >= 100 and v > 0 and len(str(int(v))) < len(str(int(old))) - 0 and v < old * 0.5:
            out.append(Check(seq=obs.seq, field=path, predicted={"value": old}, observed=v, verdict="read_error", rule="digit_count",
                             action="discard_reread"))  # fmt: skip
    return out


def check(state: GameState, obs: Observation, predictions: list[Prediction]) -> list[Check]:
    """先过不变量（read_error），再和到期预测比（consistent / model_gap），其余字段 unpredicted。"""
    try:
        from hiro.state.invariants import check_invariants  # 数据确认交付

        inv = [c if isinstance(c, Check) else Check(**{k: v for k, v in c.items() if k in Check.__dataclass_fields__})
               for c in check_invariants(state, obs)]  # fmt: skip
    except ImportError:
        inv = builtin_invariants(state, obs)
    bad = {c.field for c in inv if c.verdict == "read_error"}
    out = list(inv)
    flat = _flat(obs)
    seen: set[str] = set()
    for p in predictions:
        if p.due not in ("any", obs.page.name):
            continue
        for path, exp in p.fields.items():
            if path not in flat or path in bad or path in seen or flat[path] is None:
                continue
            seen.add(path)
            ok = exp.admits(flat[path])
            out.append(Check(seq=obs.seq, field=path, predicted=exp.to_dict() if hasattr(exp, "to_dict") else exp.__dict__,
                             observed=flat[path], verdict="consistent" if ok else "model_gap", rule="prediction",
                             action="accept" if ok else "mark_pending"))  # fmt: skip
    for path, v in flat.items():
        if v is not None and path not in bad and path not in seen:
            out.append(Check(seq=obs.seq, field=path, observed=v, verdict="unpredicted", rule="prediction", action="accept"))
    return out


def gate(obs: Observation, checks: list[Check], state: GameState | None = None) -> Observation:
    """去掉 read_error 的读数：params 的子键换回状态里的旧值（params 是整体替换的字段，不能缺项），其余字段整项去掉。返回新观测。"""
    bad = [c.field for c in checks if c.verdict == "read_error"]
    if not bad:
        return obs
    o = copy.deepcopy(obs)
    for path in bad:
        parts = path.split(".")
        if len(parts) == 3 and isinstance(o.fields.get(parts[1]), dict):
            old = _get(state, path) if state is not None else None
            sub = {k: v for k, v in o.fields[parts[1]].items() if k != parts[2]}
            if old is not None:
                sub[parts[2]] = old
            o.fields[parts[1]] = sub
        elif len(parts) >= 2:
            o.fields.pop(parts[1], None)
    return o


def mark(state: GameState, checks: list[Check]) -> GameState:
    """按 Check 更新字段状态：consistent → verified；model_gap → pending + pending_review；read_error → 记冲突；unpredicted → observed。"""
    s = copy.deepcopy(state)
    for c in checks:
        if c.verdict == "consistent":
            s.field_status[c.field] = "verified"
        elif c.verdict == "model_gap":
            s.field_status[c.field] = "pending"
            if c.field not in s.pending_review:
                s.pending_review.append(c.field)
        elif c.verdict == "read_error":
            s.conflicts.append(f"seq {c.seq}: {c.field} 读数 {c.observed!r} 违反 {c.rule}（参考 {c.predicted!r}），丢弃")
            del s.conflicts[:-20]
        elif s.field_status.get(c.field) not in ("verified", "pending"):
            s.field_status[c.field] = "observed"
    return s


def reduce_checked(state: GameState, obs: Observation, predictions: list[Prediction]) -> tuple[GameState, list[Check]]:
    """主循环与离线回放共用：互验 → 去掉读错 → reduce → 标字段状态。只对截图来源做互验；存档是真值。"""
    from hiro.loop.reduce import reduce

    if obs.source not in ("screen", "replay", "dataset") or not obs.fields:
        return reduce(state, obs), []
    checks = check(state, obs, predictions)
    return mark(reduce(state, gate(obs, checks, state)), checks), checks


def settle(predictions: list[Prediction], checks: list[Check]) -> list[Prediction]:
    """核对过的预测出队。"""
    done = {c.field for c in checks if c.verdict in ("consistent", "model_gap")}
    return [p for p in predictions if not (set(p.fields) & done)]


PAIR_WINDOW = 8  # 动作事件与识别认出的同一件事（获得弹窗、交換確認）相隔不超过这么多个 seq 就算同一件


def _pair_key(e: Event) -> tuple | None:
    a = e.args or {}
    ident = a.get("card_id") or a.get("drink_id") or a.get("pitem_id")
    if e.kind == "CARD_CHANGE":
        ident = a.get("card_id")
    if not ident:
        return None
    effect = {"CARD_ACQUIRE": "add", "SHOP_BUY": "add", "CARD_CHANGE": "add", "DRINK_ACQUIRE": "drink", "PITEM_ACQUIRE": "pitem",
              "CARD_DELETE": "delete", "CARD_UPGRADE": "upgrade"}.get(e.kind)  # fmt: skip
    return (effect, ident) if effect else None


def find_pair(event: Event, recent: list[Event]) -> Event | None:
    """recent 里与 event 是同一件事的另一来源事件（动作 ↔ 识别），按 seq 最近的配。没有返回 None。"""
    key = _pair_key(event)
    if key is None:
        return None
    for other in reversed(recent):
        if other.origin == event.origin or other.ref.get("paired"):
            continue
        if abs(other.seq - event.seq) <= PAIR_WINDOW and _pair_key(other) == key:
            return other
    return None


def to_event(d: dict | Event) -> Event:
    if isinstance(d, Event):
        return d
    return Event(**{k: v for k, v in d.items() if k in Event.__dataclass_fields__})
