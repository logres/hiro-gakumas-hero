"""Choose a card to inspect, never authorize a customization purchase.

The visit owner retains reviewed/excluded (card_id, upgrade) keys and resets
them on a new visit. This module does not route actions to any executor.
"""

from dataclasses import replace

from hiro.brain.mechanism_card_selection import _view, build_context as card_context
from hiro.brain.mechanism_customize import enabled
from hiro.brain.route_policy import ROUTE_POLICY_SKIP
from hiro.contracts import Action, ActionKind, Decision, llm_trace_from_call
from hiro.state.catalog import catalog


def _wait(reason, *, choice="wait", traces=(), source="fallback"):
    return Decision(Action(ActionKind.WAIT, {"review_only": True, "choice": choice}),
                    reason, source, None, warnings=[ROUTE_POLICY_SKIP],
                    llm=list(traces), decider="customize_card_selection")


def build_context(state, identity, candidates=None, *, complete=None,
                  reviewed=frozenset(), excluded=frozenset(), master=None):
    """Require a complete observed grid; deck ledger completeness is separate."""
    master = master or catalog()
    fields = state.page_fields
    cards = candidates if candidates is not None else fields.get("cards")
    complete = fields.get("complete") if complete is None else complete
    p, left = fields.get("produce_point"), fields.get("cards_left")
    if (not identity or complete is not True or not isinstance(cards, list)
            or type(p) is not int or p < 0 or type(left) is not int or left < 0):
        return None
    # Unknown active cells preclude claiming the complete choice set was seen.
    active = []
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            return None
        if card.get("active") is False:
            continue
        if (not isinstance(card.get("card_id"), str) or not card["card_id"]
                or type(card.get("upgrade")) is not int or card["upgrade"] < 0
                or type(card.get("customized")) is not bool
                or type(card.get("available")) is not bool
                or card.get("unknown") is True):
            return None
        physical = card.get("index", index)
        if type(physical) is not int or physical < 0:
            return None
        active.append((physical, card))
    indexes = [i for i, _ in active]
    if len(set(indexes)) != len(indexes):
        return None
    ids = [c["card_id"] for _, c in active]
    options, exclusions = [], []
    for index, card in active:
        key = (card["card_id"], card["upgrade"])
        reason = None
        if ids.count(card["card_id"]) != 1:
            reason = "Duplicate card ID cannot be uniquely selected by executor."
        elif key in reviewed or key in excluded:
            reason = "Already reviewed or explicitly excluded this visit."
        elif not card["available"]:
            reason = "Observed unavailable."

        if reason:
            exclusions.append({"index": index, "card_id": key[0], "upgrade": key[1], "reason": reason})
            continue
        row = master.card(*key)
        view = _view(*key, row, card)
        if not view["name"] or not view["master_effect_text"]:
            exclusions.append({"index": index, "card_id": key[0], "upgrade": key[1], "reason": "Master effect unknown."})
            continue
        offers = []
        for offer_id in row.get("produceCardCustomizeIds") or []:
            # Definitions are not evidence of current physical columns/prices.
            try:
                definition = master.one("ProduceCardCustomize", offer_id)
            except (KeyError, AttributeError):
                definition = {}
            offers.append({"id": offer_id, "name": definition.get("name"),
                           "definition": {k: v for k, v in definition.items()
                                          if not any(token in k.lower() for token in ("price", "cost", "level"))},
                           "basis": "master definition only; current menu, price and availability unobserved"})
        options.append({"index": index, **view, "customization_effects_unknown": card["customized"], "master_customization_offers": offers})
    idol = master.one("IdolCard", identity.replace("i_card-skin-", "i_card-"))
    payload = card_context(replace(state, page_fields={"candidates": []}), idol, {}, master)
    payload.update(candidates=options, exclusions=exclusions,
                   guidance_grid={"complete": True, "observed_cards": active and [c for _, c in active] or []},
                   cards_left=left,
                   allowed_action="review one listed card, decline, or wait; no purchase, price, levels, or guidance end",
                   limitation="Customized candidate actual effects must be inspected in the menu before any spending decision. Observed grid effects supplement the ledger; grid completeness does not establish ledger completeness. Other cards and menu options have not been previewed.")
    payload["resources"]["produce_point"] = p
    return payload


def select_card(decider, state, identity, candidates=None, *, complete=None,
                reviewed=frozenset(), excluded=frozenset(), master=None):
    if not enabled() or decider.llm is None:
        return _wait("通用定制未启用或无模型")
    try:
        payload = build_context(state, identity, candidates, complete=complete,
                                reviewed=reviewed, excluded=excluded, master=master)
        if payload is None:
            return _wait("定制完整卡列表、版本或资源未知")
        if payload["cards_left"] == 0 or not payload["candidates"]:
            return _wait("本次没有可继续审阅的卡", choice="decline")
        data, calls = decider._ask(["customize_card_selection.md"], payload)
        traces = [llm_trace_from_call(c) for c in calls]
    except Exception as exc:
        return _wait("定制选卡上下文或模型失败：" + type(exc).__name__)
    if (not isinstance(data, dict) or not isinstance(data.get("reason"), str)
            or not data["reason"].strip()):
        return _wait("定制选卡回复无效", traces=traces)
    if set(data) == {"action", "reason"} and data["action"] in ("decline", "wait"):
        return _wait(data["reason"].strip(), choice=data["action"], traces=traces, source="llm")
    if (set(data) != {"action", "reason", "index", "card_id", "upgrade"}
            or data["action"] != "review" or type(data.get("index")) is not int
            or type(data.get("upgrade")) is not int):
        return _wait("定制选卡回复越界", traces=traces)
    match = next((c for c in payload["candidates"] if all(data[k] == c[k]
                 for k in ("index", "card_id", "upgrade"))), None)
    if match is None:
        return _wait("定制选卡目标不在当前可审阅列表", traces=traces)
    return Decision(Action(ActionKind.CUSTOMIZE_CARD,
                           {"review_only": True, "card_id": match["card_id"], "upgrade": match["upgrade"]}),
                    data["reason"].strip(), "llm", None, warnings=[ROUTE_POLICY_SKIP],
                    llm=traces, decider="customize_card_selection")

