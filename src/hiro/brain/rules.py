# 来源：digital-hiro src/hiro/brain/rules.py @ c3fc27f（GPL-3.0-or-later）
"""规则层：显然的情形直接出结果，LLM 的输出在执行前过一遍硬约束。

硬约束只收「已经在实机里犯过、且能用公开状态判定」的错误，不做策略偏好：
- 持续/预约得分还没结算完时清空元气（2026-10-24 Claude 局 R2 第 8 回合）
- 打不可用的牌、选不存在的槽位
- 复制饮料喝下去时手里没有可接的主动卡
- 最后一回合手里还有可打的牌却跳过；最后一个行动不兑现元气（2026-10-31 三局选拔② 局末剩 309 / 579 元气、末回合 Skip）
- 复制效果待生效时先打了别的主动卡（第 1 局复制被 輝くキミへ 吃掉，せのびの魔法 只触发一次）
- 行动已用完还喝抽牌饮料（第 2 局第 9 回合）
"""

import math
from dataclasses import dataclass, field

from hiro.brain.state import BattleState


@dataclass
class Decision:
    action: str  # play:<slot> / drink:<slot> / skip
    reason: str
    source: str  # rule / plan / llm / fallback
    plan: list[dict] = field(default_factory=list)  # 本回合后续打算（LLM 给出）
    line: str = ""  # 数字小广的台词，视频用
    warnings: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return self.action.split(":")[0]

    @property
    def slot(self) -> int | None:
        return int(self.action.split(":")[1]) if ":" in self.action else None


def trivial(state: BattleState) -> Decision | None:
    """不需要思考的情形。"""
    playable = [c for c in state.hand if c.available and c.card_id]
    if not playable and not state.drinks:
        return Decision("skip", "没有可打的牌，也没有饮料", "rule")
    return None


def _known_last_turn(state: BattleState) -> bool:
    """确知是最后一回合。剩余回合没读到时按「不是最后一回合」处理：宁可不打终结，也不把未知当成最后一回合。"""
    return state.remaining_turns is not None and state.remaining_turns <= 1


def _hp_next_turn(state: BattleState, hp_cost: int) -> int | None:
    if state.hp is None:
        return None
    return state.hp - hp_cost


def violations(state: BattleState, decision: Decision) -> list[str]:
    """返回违反的硬约束；空列表表示可以执行。"""
    if decision.action not in state.legal_actions():
        return [f"{decision.action} 不在合法动作里：{state.legal_actions()}"]
    out = []
    if decision.kind == "play" and not state.action_previews:
        # 有模拟预演时由预演的期望分定夺（2026-10-30：R2 种子 2 第 12 回合，这条约束拦下了比结束回合高 11 万分的终结）
        card = next(c for c in state.hand if c.slot == decision.slot)
        if card.tags.clears_genki and not _known_last_turn(state):
            for e in state.installed:
                if e.kind in ("sustained", "delayed") and (e.turns_left or 0) > 0:
                    out.append(f"{e.name} 还有 {e.turns_left} 次按元气结算，现在打 {card.name} 清空元气会让它们落空")
                # エウレカ（永久、半血时按元气 40%）不再硬拦：它每回合只按元气 40% 得分，届いて！ 一次 400%，提前兑现常常更划算。
                # 2026-10-31 エウレカ 才被正确记为已装，这条约束一生效，bench（brain-rules，20 种子）r2 均分降 10%；改为 soft_warnings 提醒。
    if decision.kind == "drink":
        drink = next(d for d in state.drinks if d.slot == decision.slot)
        if drink.repeats_card and not any(
            c.available and c.category == "active" for c in state.hand
        ):
            out.append(f"{drink.name} 复制下一张主动卡，但手里没有可用的主动卡")
        elif drink.repeats_card and state.actions_left == 0 and not any(state.gives_action(c) for c in state.hand if c.available):
            # 第七局选拔② 剩 5 回合：行动用完后喝复制，デイドリーミング+ 没打出去，复制落到下回合的 がむしゃら++
            out.append(f"本回合行动已用完（actions_left=0），喝 {drink.name} 后没有行动打要复制的卡，复制会落到下回合别的牌上")
        if state.actions_left == 0 and "引く" in drink.text:
            out.append(f"本回合行动已用完（actions_left=0），喝 {drink.name} 抽到的牌没机会打，只会被送进弃牌堆")
    out += _last_turn_violations(state, decision)
    out += _item_budget_violations(state, decision)
    if decision.kind == "play" and state.copy_pending:
        card = next(c for c in state.hand if c.slot == decision.slot)
        target = state.repeat_target
        if card.category == "active" and target and card.name != target and any(c.name == target and c.available for c in state.hand):
            out.append(f"复制效果待生效：下一张主动卡要打 {target}（喝复制饮料时的计划），先打 {card.name} 会把复制吃掉")
    return out


def _item_budget_violations(state: BattleState, decision: Decision) -> list[str]:
    """エウレカ 已装、剩余 > 4 回合、道具只剩 ≤ 2 次时，不在 HP 过半时打固有道具的触发牌（会用掉 1 次），
    留给最后 4 回合压血触发エウレカ（第 3 局复盘 §4.2-5）。有预演时由预演定夺。"""
    if decision.kind != "play" or state.action_previews or not state.eureka_check():
        return []
    if state.remaining_turns is None or state.remaining_turns <= 4 or state.item_charges_left is None or state.item_charges_left > 2:
        return []
    card = next(c for c in state.hand if c.slot == decision.slot)
    line = state.half_line()
    if card in state.item_trigger_in_hand() and state.hp is not None and line is not None and state.hp > line:
        drop = max(1, state.max_hp * 15 // 100) if state.max_hp else 0
        if state.hp - card.hp_cost - drop <= line:
            return []  # 这次用道具正好把 HP 压到半血线以下、下回合エウレカ触发：这就是道具次数的用途（第六局选拔③ 因这条一直不压血，エウレカ 0 次）
        return [f"道具只剩 {state.item_charges_left} 次、还有 {state.remaining_turns} 回合：HP {state.hp}>{line} 时打 {card.name} 会用掉 1 次道具、"
                "却压不到半血线以下，要留到压得下去的时候"]
    return []


def _playable(state: BattleState) -> list:
    return [c for c in state.hand if c.available and c.card_id and not c.tags.is_sleep]


def _cash_out_cards(state: BattleState) -> list:
    """现在就能打、打出立刻按元气 / 好印象得分的牌（条件明确不满足的除外）。"""
    out = []
    for c in _playable(state):
        t = c.tags
        if not (t.genki_score_pct or t.impression_score_pct):
            continue
        if t.genki_min is not None and state.genki is not None and state.genki < t.genki_min:
            continue
        amount = state.genki if t.genki_score_pct else state.impression
        if amount is not None and amount <= 0:
            continue
        out.append(c)
    return out


def _last_turn_violations(state: BattleState, decision: Decision) -> list[str]:
    """最后一回合：有牌可打不许跳过；没有预演时，最后一个行动必须兑现（或打不减行动的牌），不能留着元气 / 好印象。"""
    if state.remaining_turns != 1:
        return []
    playable = _playable(state)
    from hiro.brain.route_policy import legacy_exam_policy

    # Playable does not mean profitable: an impression-cost motivation card
    # can reduce the final settlement when no motivation payoff remains.
    if decision.kind == "skip" and playable and legacy_exam_policy(state):
        cash = _cash_out_cards(state)
        hint = f"，其中能兑现的：{'、'.join(c.name for c in cash)}" if cash else ""
        return [f"最后一回合还有可打的牌（{'、'.join(c.name for c in playable)}{hint}），跳过等于白白放弃这些分数"]
    if decision.kind != "play" or state.action_previews or state.actions_left is None or state.actions_left > 1:
        return []
    card = next(c for c in state.hand if c.slot == decision.slot)
    cash = [c for c in _cash_out_cards(state) if c.slot != card.slot]
    if not cash or state.gives_action(card) or card.tags.genki_score_pct or card.tags.impression_score_pct:
        return []
    if not legacy_exam_policy(state):
        if _cash_costs_unproven(cash) or _direct_badge_not_proven_worse(card, cash, 1):
            return []
    return [f"最后一回合只剩 1 次行动，{card.name} 不兑现也不追加行动；应打兑现牌 {'、'.join(c.name for c in cash)}，"
            f"否则元気 {state.genki if state.genki is not None else '?'} / 好印象 {state.impression if state.impression is not None else '?'} 全部浪费"]


def soft_warnings(state: BattleState, decision: Decision) -> list[str]:
    """不拦截、只提醒（写进记录，也回给 LLM）。"""
    out = []
    if decision.kind == "play":
        card = next(c for c in state.hand if c.slot == decision.slot)
        if card.tags.clears_genki and not _known_last_turn(state) and card.slot not in {r["slot"] for r in _cash_now_finishers(state)}:
            out.append(f"非末回合打出清空元气的 {card.name}：须比较留着的收益（keep_value_upper）与抽不回来的风险（redraw_chance）")
    chosen = next((c for c in state.hand if c.slot == decision.slot), None) if decision.kind == "play" else None
    free = decision.kind == "drink" or (chosen is not None and state.gives_action(chosen))  # 不耗行动的先打，不算放弃
    if not free:
        for row in _cash_now_finishers(state):
            if chosen is not None and chosen.slot == row["slot"]:
                continue
            out.append(f"末段手握 {row['card']}（现在约 {row['value']:,} {row['unit']}）却不打：之后再抽到它的概率约 {row['redraw']:.0%}，"
                       f"按最后一回合倍率与元气增长 ×{row['ratio']:.2f} 算留着的期望约 {row['hold']:,} {row['unit']}（含已装效果 {row['keep']:,}）；"
                       "没抽到的话这些元气只能靠不清零的兑现牌")  # fmt: skip
    if decision.kind == "play":
        card = next(c for c in state.hand if c.slot == decision.slot)
        if card.tags.clears_genki and not _known_last_turn(state) and state.max_hp:
            hp_next = _hp_next_turn(state, card.hp_cost)
            for e in state.installed:
                if e.kind == "permanent" and "体力が50%以下" in e.note and hp_next is not None and hp_next * 2 <= state.max_hp:
                    out.append(f"{e.name} 的半血得分下回合会触发（预计 HP {hp_next}/{state.max_hp}），清空元气会让它这次落空")
    if decision.kind == "play":
        card = next(c for c in state.hand if c.slot == decision.slot)
        t = card.tags
        if t.once and t.genki_score_pct and not t.clears_genki and state.remaining_turns is not None and state.remaining_turns > EARLY_CASH_TURNS:
            out.append(f"{card.name} 是「レッスン中1回」的兑现牌，剩 {state.remaining_turns} 回合就打：元气 / やる気还低，后段打分高得多"
                       "（第六局选拔③ 剩 11 回合打 あのときの約束 4.4k，第 4 局剩 3 回合打 20k）")  # fmt: skip
    swap = None
    if decision.kind == "play":
        card = next(c for c in state.hand if c.slot == decision.slot)
        swap = card.name if "手札をすべて入れ替える" in card.text else None
    elif decision.kind == "drink":
        drink = next((x for x in state.drinks if x.slot == decision.slot), None)
        swap = drink.name if drink and "手札をすべて入れ替える" in drink.text else None
    if swap:
        cores = [c.name for c in state.hand if c.name != swap and (c.tags.sustained_turns or c.tags.delayed_turns or c.tags.clears_genki)]
        if cores:
            out.append(f"{swap} 会换掉全部手牌：{'、'.join(cores)} 会进弃牌堆，要等洗牌才回来"
                       "（第六局选拔③ 第 1 回合这样洗掉开局的 デイドリーミング+，剩 3 回合才打出，4 次结算只剩 2 次）")  # fmt: skip
    if decision.kind == "drink" and state.remaining_turns is not None and state.remaining_turns > 8:
        drink = next((x for x in state.drinks if x.slot == decision.slot), None)
        same = [x for x in state.drinks if drink and x.name == drink.name]
        if drink and "使用数追加" in drink.text and len(same) <= 1 and not any("使用数追加" in x.text for x in state.drinks if x is not drink):
            out.append(f"{drink.name} 是最后一瓶加行动饮料，剩 {state.remaining_turns} 回合就喝：末段连打兑现时没有了")
    if decision.kind == "skip":
        if any(c.available and c.card_id and not c.tags.is_sleep for c in state.hand):
            out.append("手里还有可打的牌却跳过回合（回复 2 体力）")
    return out


EARLY_CASH_TURNS = 4  # 「レッスン中1回」的按比例兑现牌，剩余回合多于它时打出算过早
FINISHER_HOLD_TURNS = 4  # 剩余回合 ≤ 它时，终结牌在手就比较「现在打」与「留着」


def _cash_now_finishers(state: BattleState) -> list[dict]:
    """非末回合、剩余 ≤ FINISHER_HOLD_TURNS 回合时按期望该现在打的终结牌：现在的得分 > 再抽到的概率 × 得分 × 最后一回合倍率比 × 元气增长 + 已装效果。
    只用于 soft_warnings 提醒，不进兜底：bench（brain-rules 20 种子）里接进兜底，r1 / r2 均分都降（137–142k / 233–255k 对 142k / 248k），
    亏的局都是 redraw_chance 偏低、实际靠 紙吹雪「下回合多抽 2 张」等抽牌又抽回来了（概率模型不算抽牌牌，bench 牌组小、抽牌多）。
    牌堆读不到（redraw_chance 未知）时不判。"""
    if _known_last_turn(state) or state.remaining_turns is None or state.remaining_turns > FINISHER_HOLD_TURNS:
        return []
    checks = {r["card"]: r for r in state.finisher_check() or []}
    cash = {r["card"]: r for r in state.cash_out_check() or []}
    out = []
    for c in state.hand:
        r = checks.get(c.name)
        if not (c.available and r and isinstance(r.get("redraw_chance"), float)):
            continue
        value = c.badge_score if c.badge_score is not None else cash.get(c.name, {}).get("预计得分")
        ratio = (r.get("final_turn_ratio") or 1.0) * (r.get("genki_growth_est") or 1.0)
        if isinstance(value, int) and ("keep_value_upper" in r or not r.get("keep_genki_pct")):
            keep, unit = r.get("keep_value_upper") or 0, "分"
        elif c.tags.genki_score_pct:  # 倍率 / 徽章不全（模拟器 bench）：按元气百分比比较，本回合倍率两边约掉
            value, keep, unit = c.tags.genki_score_pct, r.get("keep_genki_pct") or 0, "% 元气"
        else:
            continue
        hold = r["redraw_chance"] * value * ratio + keep  # 留着：再抽到时在最后一回合按更高倍率、更多元气打 + 已装效果
        if value > hold:
            out.append({"card": c.name, "slot": c.slot, "value": value, "redraw": r["redraw_chance"], "keep": keep, "unit": unit,
                        "hold": math.ceil(hold), "ratio": ratio})  # fmt: skip
    return out


def fallback(state: BattleState) -> Decision:
    """LLM 不可用时的兜底：有模拟预演就选期望终局分最高的合法动作；否则用启发式
    （追加行动/抽牌 > 安装持续 > 其他非终结牌 > 跳过；末回合才打终结）。"""
    legal = set(state.legal_actions())
    for row in state.action_previews or []:
        if row.get("legal_action") in legal:
            return Decision(row["legal_action"], f"兜底：预演期望终局分最高（{row['期望终局分']:,}）", "fallback")
    from hiro.brain.fallback_drinks import action_drink_decision, best_direct_impression_action
    if (drink_decision := action_drink_decision(state)) is not None:
        return drink_decision
    last = _known_last_turn(state)
    cands = [c for c in state.hand if c.available and c.card_id and not c.tags.is_sleep]
    if not cands:
        return Decision("skip", "兜底：没有可打的牌", "fallback")

    cash = _cash_out_cards(state)
    many_actions = state.actions_left is not None and state.actions_left > 1
    if (not cash and state.impression is not None
            and not any(state.gives_action(c) for c in cands)):
        if (setup := best_direct_impression_action(state)) is not None:
            slot, gain = setup
            return Decision(f"play:{slot}", f"末回合无即时兑现牌：优先可支付的直接好印象 +{gain}（层数，非分数），出牌后重读", "fallback")

    def score(c) -> float:
        t = c.tags
        # エウレカ（「以降、ターン開始時」）2026-10-31 起记为永久触发；兜底不给它装填分，与改前一致（bench 逐分相同）
        s = 3.0 * t.extra_actions + 1.5 * t.draws + (2.5 if t.sustained_turns or (t.permanent_trigger and "以降、ターン開始時" not in c.text) else 0)
        if last and state.gives_action(c):
            s += 12  # 末回合：先打不减行动的牌，再兑现
        if c in cash and not t.clears_genki:
            s += (6 + (t.genki_score_pct or t.impression_score_pct) / 100) if last else 0  # 末回合：不清零元气的兑现牌优先
        if t.clears_genki:
            s += (10 - (3 if many_actions and len(cash) > 1 else 0)) if last else -20  # 末回合还有别的兑现牌和行动时先打它们
        if t.genki_score_pct and state.genki == 0 and "元気+" not in c.text:
            s -= 30  # 元気为 0：按元気得分的牌打出去 0 分（q11 选拔② 末回合 届いて 清零后又打 紙吹雪++，用户批注）
        return s - 0.2 * (c.cost + 2 * c.hp_cost)

    best = max(cands, key=score)
    d = Decision(f"play:{best.slot}", "兜底启发式", "fallback")
    if violations(state, d):
        others = [c for c in cands if c is not best and not c.tags.clears_genki]
        if not others:
            return Decision("skip", "兜底：唯一可打的是会清空元气的终结牌", "fallback")
        best = max(others, key=score)
        d = Decision(f"play:{best.slot}", "兜底启发式（避开终结牌）", "fallback")
    return d


def _cash_value(state: BattleState, card) -> int | None:
    """这张兑现牌现在打的得分：徽章（已过读错检查）优先，否则公式。"""
    return card.badge_score if card.badge_score is not None else state.cash_formula(card)


def _cash_costs_unproven(cards) -> bool:
    """Cash-only totals omit lost impression settlement and unknown costs."""
    for card in cards:
        cost = card.extra_cost
        if cost is None:
            continue
        if not isinstance(cost, dict):
            return True
        kind, value = cost.get("type"), cost.get("value")
        if (kind not in ("ExamCostType_ExamReview", "ExamCostType_ExamCardPlayAggressive")
                or type(value) is not int or value < 0):
            return True
        if kind == "ExamCostType_ExamReview" and value > 0:
            return True
    return False


def _direct_badge_not_proven_worse(card, cash, actions: int) -> bool:
    """An incomplete cash-only estimate cannot displace observed direct output."""
    if card.tags.genki_score_pct or card.tags.impression_score_pct or type(card.badge_score) is not int:
        return False
    if any(type(c.badge_score) is not int for c in cash):
        return True  # formula omits modifiers; unknown is not zero
    upper = sum(sorted((c.badge_score for c in cash), reverse=True)[:actions])
    return card.badge_score > upper


def final_turn_plan(state: BattleState) -> dict | None:
    """最后一回合（画面剩余 1）的最佳兑现：耗行动的牌只能再打 actions_left 张，按真实得分挑；清空元气的终结牌放最后，
    最多一张（清空后别的元気牌没分）。不耗行动的牌（使用数追加 / 触发固有道具）不占名额。没有可兑现的牌时返回 None。"""
    if state.remaining_turns != 1:
        return None
    candidates = [c for c in _cash_out_cards(state) if not state.gives_action(c)]
    from hiro.brain.route_policy import legacy_exam_policy

    if not legacy_exam_policy(state) and _cash_costs_unproven(candidates):
        return None
    cash = [(c, _cash_value(state, c)) for c in candidates]
    cash = [(c, v) for c, v in cash if v]
    if not cash:
        return None
    n = max(1, state.actions_left if state.actions_left is not None else 1)
    keep = sorted([x for x in cash if not x[0].tags.clears_genki], key=lambda x: -x[1])
    clear = sorted([x for x in cash if x[0].tags.clears_genki], key=lambda x: -x[1])
    options = [keep[:n]]
    if clear:
        options.append(keep[: n - 1] + clear[:1])
    best = max(options, key=lambda o: sum(v for _, v in o))
    best.sort(key=lambda x: x[0].tags.clears_genki)  # 清空元气的放最后
    return {"cards": [c for c, _ in best], "values": [v for _, v in best], "total": sum(v for _, v in best), "actions": n}


def final_turn_override(state: BattleState, decision: Decision) -> Decision | None:
    """最后一回合有兑现牌时，按「真实收益最大」强制：要打的耗行动牌不在最佳组合里、清空元气的终结牌打在别的兑现牌前面、
    或跳过回合，都改成最佳组合的下一张。不耗行动的牌和饮料不拦（不占名额，可能还加元気 / 行动）。"""
    plan = final_turn_plan(state)
    if plan is None or decision.kind == "drink":
        return None
    first = plan["cards"][0]
    if decision.kind == "play":
        card = next((c for c in state.hand if c.slot == decision.slot), None)
        if card is None or state.gives_action(card):
            return None
        from hiro.brain.route_policy import legacy_exam_policy

        if (not legacy_exam_policy(state) and decision.action in state.legal_actions()
                and _direct_badge_not_proven_worse(card, plan["cards"], plan["actions"])):
            return None
        # The cash-only plan does not simulate setup -> cash-out. With another
        # action available it cannot prove that spending one action on a buff is
        # inferior (r6 seq24: impression +5 was forced AFTER its 100% cash-out).
        # Keep single-action protection and ordering of resource-clearing cards.
        import os
        if (os.environ.get("HIRO_FINAL_TURN_SETUP") == "1"
                and state.actions_left is not None and state.actions_left > 1
                and decision.action in state.legal_actions()
                and not card.tags.clears_genki and card not in _cash_out_cards(state)):
            return None
        if card.slot == first.slot or (card in plan["cards"] and not card.tags.clears_genki):
            return None
        why = (f"{card.name} 不在最佳兑现组合里" if card not in plan["cards"] else f"{card.name} 会清空元気，应放在最后")
    else:
        why = "跳过回合会放弃兑现"
    names = "、".join(f"{c.name}（约 {v:,}）" for c, v in zip(plan["cards"], plan["values"]))
    steps = [{"action": "play", "card": c.name} for c in plan["cards"][1:]]
    return Decision(f"play:{first.slot}", f"最后一回合：耗行动的牌只够再打 {plan['actions']} 张，按真实得分打 {names}，合计约 {plan['total']:,}；"
                    f"{why}（代码计算，覆盖原决策 {decision.action}）", "rule", plan=steps)  # fmt: skip
