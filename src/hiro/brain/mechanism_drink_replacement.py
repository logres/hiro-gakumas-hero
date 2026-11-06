"""Opt-in whole-holding comparison for full drink slots, with bounded actions."""
import os
from dataclasses import replace
from itertools import combinations

from hiro.brain.cards import description_text
from hiro.brain.mechanism_card_selection import build_context as card_context
from hiro.contracts import Action, ActionKind, Candidate, Decision, llm_trace_from_call
from hiro.state.catalog import CatalogUnavailable, catalog


def enabled():
    return os.environ.get("HIRO_MECHANISM_DRINK_REPLACEMENT") == "1"


def _center(item):
    center = item.get("center")
    return (isinstance(center, (list, tuple)) and len(center) == 2
            and all(type(v) is int for v in center) and 0 <= center[0] < 720 and 0 <= center[1] < 1280)


def build_context(state, identity, *, page, can_skip=True, n_options=None):
    """Enumerate executable results; model output can only select an option ID."""
    pf, produce = state.page_fields, state.produce or {}
    if page not in ("SELECT_DRINK", "PDRINK_MAX") or type(can_skip) is not bool:
        return None, "饮料替换页面或跳过权限未知"
    held = pf.get("held")
    if not isinstance(held, list) or not 1 <= len(held) <= 4:
        return None, "当前持有饮料不完整"
    capacity = produce.get("drink_capacity")
    if page == "PDRINK_MAX" and pf.get("complete") is True and capacity is None:
        capacity = len(held)  # Complete overflow list proves the full slot count.
    if type(capacity) is not int or not 1 <= capacity <= 4 or capacity != len(held):
        return None, "当前满栏容量未核实或持有张数不符"
    if page == "SELECT_DRINK":
        if pf.get("full") is not True:
            return None, "当前饮料满栏未确认"
        raw = pf.get("candidates")
        if not isinstance(raw, list) or not 1 <= len(raw) <= 3:
            return None, "全部候选饮料未识别"
        if n_options is not None and (type(n_options) is not int or n_options != len(raw)):
            return None, "候选数量与页面不一致"
        if any(not isinstance(item,dict) or any(key in item and
               (type(item[key]) is not int or item[key] != i) for key in ("index","slot"))
               for i,item in enumerate(raw)):
            return None,"候选物理索引与页面顺序不一致"
        incoming = [dict(item, index=i) if isinstance(item, dict) else item for i, item in enumerate(raw)]
    else:
        if pf.get("complete") is not True:
            return None, "溢出列表未完整识别"
        incoming = pf.get("incomings")
        if incoming is None and isinstance(pf.get("incoming"), dict):
            incoming = [pf["incoming"]]
        if not isinstance(incoming, list) or not 1 <= len(incoming) <= 4:
            return None, "全部新饮料未识别"
    try:
        master = catalog()
        idol = master.one("IdolCard", identity.replace("i_card-skin-", "i_card-")) if identity else None
        if not idol or not idol.get("examEffectType") or idol["examEffectType"].endswith("_Unknown"):
            return None, "当前偶像机制主数据未知"
        def details(items, *, owned):
            out = []
            for item in items:
                if (not isinstance(item, dict) or type(item.get("index")) is not int
                        or not 0 <= item["index"] < (capacity if owned else len(incoming))
                        or not isinstance(item.get("drink_id"), str) or not item["drink_id"]):
                    raise ValueError("饮料身份或原始索引未知")
                row = master.one("ProduceDrink", item["drink_id"])
                text = description_text(row.get("produceDescriptions"))
                if not text:
                    raise ValueError("饮料效果未知")
                visible = item.get("visible") is not False
                if visible and not _center(item) and (owned or page == "PDRINK_MAX"):
                    raise ValueError("当前饮料操作位置未知")
                out.append({"index": item["index"], "drink_id": item["drink_id"],
                            "name": row.get("name"), "effects": text, "visible": visible})
            if {v["index"] for v in out} != set(range(len(items))):
                raise ValueError("饮料原始索引重复或缺失")
            return out
        owned, offered = details(held, owned=True), details(incoming, owned=False)
        shared = card_context(replace(state, page_fields={"candidates": []}), idol, {}, master)
    except (CatalogUnavailable, KeyError, OSError, ValueError, AttributeError) as exc:
        return None, "饮料替换证据不足：" + str(exc)
    options = []
    def option(discard, receive):
        result = [h["drink_id"] for h in owned if h["index"] not in discard]
        result += [n["drink_id"] for n in offered if n["index"] in receive]
        args = {"discard": sorted(discard), "receive": bool(receive), "receive_indexes": sorted(receive)}
        if page == "SELECT_DRINK" and receive:
            args["pick_index"] = receive[0]
        options.append({"option_id": str(len(options)), "action_args": args, "resulting_drinks": result})
    if can_skip:
        option([], [])
    visible_owned = [h for h in owned if h["visible"]]
    visible_new = [n for n in offered if n["visible"]]
    max_take = 1 if page == "SELECT_DRINK" else min(len(visible_owned),len(visible_new))
    for count in range(1,max_take+1):
        for take in combinations(visible_new,count):
            for drop in combinations(visible_owned,count):
                option([h["index"] for h in drop],[n["index"] for n in take])
    if not options:
        return None, "没有已核实可执行的饮料组合"
    return {"page":page, "capacity":capacity, "can_skip":can_skip,
            "identity_mechanisms":shared["identity_mechanisms"], "deck":shared["deck"],
            "stage":{"mode":produce.get("mode"),"step":produce.get("step")},
            "known_resources":{k:produce.get(k) for k in ("stamina","max_stamina","produce_point")},
            "held":owned,"incoming":offered,"options":options},None


def choose(decider,state,identity,*,page,can_skip=True,n_options=None):
    calls=[]
    def wait(reason):
        return Decision(Action.ui(ActionKind.WAIT,why=reason),reason,"fallback",.1,
                        llm=[llm_trace_from_call(c) for c in calls],decider="mechanism_drink_replacement")
    payload,error=build_context(state,identity,page=page,can_skip=can_skip,n_options=n_options)
    if error:
        return wait(error)
    if decider.llm is None:
        return wait("饮料组合比较没有模型，不自动丢弃或放弃新饮料")
    try:
        data,calls=decider._ask(["mechanism_drink_replacement.md"],payload)
    except Exception as exc:
        return wait("饮料组合模型调用失败："+type(exc).__name__)
    if (not isinstance(data,dict) or set(data)!={"option_id","reason"}
            or not isinstance(data["option_id"],str) or not isinstance(data["reason"],str)
            or not data["reason"].strip() or len(data["reason"])>1000):
        return wait("饮料组合模型回复无效，不执行")
    selected=next((o for o in payload["options"] if o["option_id"]==data["option_id"]),None)
    if selected is None:
        return wait("饮料组合模型选项越界，不执行")
    def action(o):
        return Action(ActionKind.DISCARD_DRINK,{**o["action_args"],"mechanism_replacement":True})
    return Decision(action(selected),data["reason"],"llm",None,
                    [Candidate(action(o),preview=o) for o in payload["options"]],
                    llm=[llm_trace_from_call(c) for c in calls],decider="mechanism_drink_replacement")


def same_drink_identities(expected,fresh,*,page):
    """Fresh screen identity gate before any discard; no positional fallbacks."""
    if not isinstance(fresh,dict):
        return False
    if page=="SELECT_DRINK" and fresh.get("full") is not True:
        return False
    if page=="PDRINK_MAX" and fresh.get("complete") is not True:
        return False
    def keys(fields,key):
        items=fields.get(key)
        if not isinstance(items,list):
            return None
        result=[]
        for i,item in enumerate(items):
            if not isinstance(item,dict) or not item.get("drink_id"):
                return None
            if key=="candidates" and any(name in item and
                    (type(item[name]) is not int or item[name] != i) for name in ("index","slot")):
                return None
            index=i if key=="candidates" else item.get("index")
            if type(index) is not int:
                return None
            result.append((index,item["drink_id"]))
        return sorted(result)
    incoming_key="candidates" if page=="SELECT_DRINK" else "incomings"
    expected_positions={h.get("index"):list(h["center"]) for h in expected.get("held") or []
                        if isinstance(h,dict) and _center(h) and h.get("visible") is not False}
    fresh_positions={h.get("index"):list(h["center"]) for h in fresh.get("held") or []
                     if isinstance(h,dict) and _center(h) and h.get("visible") is not False}
    return (expected_positions==fresh_positions
            and keys(expected,"held") is not None and keys(expected,"held")==keys(fresh,"held")
            and keys(expected,incoming_key) is not None
            and keys(expected,incoming_key)==keys(fresh,incoming_key))
