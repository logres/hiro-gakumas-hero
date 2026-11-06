# 来源：digital-hiro hiro/kaa_env.py（c3fc27f）；调用 KAA（kotones-auto-assistant，GPL-3.0）；开源版：编成号 / 方案名改成环境变量
"""用代码构造 KAA 运行所需的 profile 与培育方案，不经 KAA 图形界面。

KAA 的培育流程通过 `kaa_context.conf()` / `produce_solution()` 读取配置；方案文件写在工作目录的 conf/ 下（别提交）。

环境变量：
- HIRO_SUPPORT_SET（new 必填）：支援卡编成号（1–20）。开局的租借格由 hiro.loop.kaa_patches 处理：编成已满直接下一步，
  租借格空着就停下（RentalPending），不让 KAA 直接确认列表第一张。写 auto = 用 KAA「おまかせ」（KAA 自己选支援卡和租借，
  会确认列表第一张租借卡），只有明确想这样时才写。
- HIRO_MEMORY_SET（new 必填）：回忆（メモリー）编成号。写 auto = おまかせ（会改写当前编成位，可能带进和本局方向冲突的牌）。
- HIRO_MEMORY_CARDS：回忆编成对应的技能卡 ID，逗号分隔（如 p_card-02-men-2_004,p_card-02-act-1_037）。
- HIRO_MEMORY_CARD_TIMINGS：与上列卡逐项对应的 start / mid / unknown，逗号分隔；仅 start 开局就算已有。
  不设 = 时机未知，不预先计入；方案里的 memory.chosen[].timing 可自动提供对应时机。
- HIRO_KAA_PROFILE / HIRO_KAA_SOLUTION：KAA 的 profile 名与培育方案名（默认 hiro / hiro-gakumas）。
- HIRO_FORMATION_PLAN：开局编成方案文件（默认 conf/formation-plan.json，由 python -m hiro.brain.formation_plan 生成；off = 不读）。
  方案存在、且方案的偶像和这局一致时，上面三个变量没设的部分用方案里的值（支援卡 / 回忆编成号、回忆带的卡），
  主属性默认用方案的；开局第 2 / 3 步按方案核对编成，对不上就停（见 docs/formation-plan.md）。环境变量写了的以环境变量为准。
resume 不读编成号（培育已经开始）。
"""

from __future__ import annotations

import logging
import os

PROFILE_NAME = os.environ.get("HIRO_KAA_PROFILE") or "hiro"
SOLUTION_NAME = os.environ.get("HIRO_KAA_SOLUTION") or "hiro-gakumas"


AUTO = "auto"


def _set_env(name: str) -> int | str | None:
    """编成号：整数、"auto"（おまかせ）或 None（没设）。"""
    v = (os.environ.get(name) or "").strip()
    if not v:
        return None
    if v.lower() == AUTO:
        return AUTO
    try:
        return int(v)
    except ValueError:
        raise ValueError(f"{name} 应为编成号（整数）或 auto，收到 {v!r}") from None


SUPPORT_SET = _set_env("HIRO_SUPPORT_SET")
MEMORY_SET = _set_env("HIRO_MEMORY_SET")
MEMORY_CARDS = tuple(c.strip() for c in (os.environ.get("HIRO_MEMORY_CARDS") or "").split(",") if c.strip())
_MEMORY_CARD_TIMINGS_CONFIG = tuple(t.strip().lower() for t in (os.environ.get("HIRO_MEMORY_CARD_TIMINGS") or "").split(",") if t.strip())


def _checked_memory_timings(cards: tuple[str, ...], timings: tuple[str, ...]) -> tuple[str, ...]:
    """Missing timing means unknown, never an assumed opening card."""
    if not timings:
        return ("unknown",) * len(cards)
    if len(timings) != len(cards) or any(t not in {"start", "mid", "unknown"} for t in timings):
        raise ValueError("HIRO_MEMORY_CARD_TIMINGS 须与回忆卡逐项对应，值为 start、mid 或 unknown")
    return timings


MEMORY_CARD_TIMINGS = _checked_memory_timings(MEMORY_CARDS, _MEMORY_CARD_TIMINGS_CONFIG) if MEMORY_CARDS else ()


def start_memory_cards() -> tuple[str, ...]:
    """Only confirmed opening acquisitions may seed ownership before any trace event."""
    return tuple(card for card, timing in zip(MEMORY_CARDS, MEMORY_CARD_TIMINGS) if timing == "start")


class SetupMissing(ValueError):
    """new 开局缺编成号。"""


logger = logging.getLogger(__name__)
ACTIVE_PLAN: dict | None = None  # init_kaa 采用的开局编成方案（kaa_patches 第 2 / 3 步按它核对）
PLAN_MAIN_ATTR: str | None = None


def apply_formation_plan(idol: str | None, path: str | None = None) -> dict | None:
    """读开局编成方案；环境变量没设的编成号 / 回忆卡与其入手时机用方案的。偶像对不上时不用。"""
    global SUPPORT_SET, MEMORY_SET, MEMORY_CARDS, MEMORY_CARD_TIMINGS, ACTIVE_PLAN, PLAN_MAIN_ATTR
    from hiro.brain.formation_plan import PLAN_PATH, load

    env = os.environ.get("HIRO_FORMATION_PLAN")
    ACTIVE_PLAN, PLAN_MAIN_ATTR = None, None
    if env == "off":
        return None
    plan = load(path or env or PLAN_PATH)
    if not plan:
        return None
    want = (plan.get("idol") or {}).get("idol_card_id")
    if idol and want and idol.replace("i_card-skin-", "i_card-") != want:
        logger.warning("开局编成方案是给 %s 的，这局是 %s：不用方案", want, idol)
        return None
    sup, mem = plan.get("support") or {}, plan.get("memory") or {}
    if SUPPORT_SET is None and sup.get("set") and sup.get("own"):
        SUPPORT_SET = int(sup["set"])
    if MEMORY_SET is None and mem.get("set") and mem.get("cards"):
        MEMORY_SET = int(mem["set"])
    if not MEMORY_CARDS and mem.get("cards"):
        MEMORY_CARDS = tuple(mem["cards"])
        by_card = {row.get("card_id"): row.get("timing") for row in mem.get("chosen") or [] if row.get("card_id")}
        timings = _MEMORY_CARD_TIMINGS_CONFIG or tuple(by_card.get(card) if by_card.get(card) in {"start", "mid"} else "unknown"
                                                     for card in MEMORY_CARDS)
        MEMORY_CARD_TIMINGS = _checked_memory_timings(MEMORY_CARDS, timings)
    ACTIVE_PLAN, PLAN_MAIN_ATTR = plan, plan.get("main_attr")
    logger.info("开局编成方案（%s）：支援卡编成 %s、回忆编成 %s、主属性 %s、回忆带的卡 %s", plan.get("created"), SUPPORT_SET, MEMORY_SET,
                PLAN_MAIN_ATTR, "/".join(MEMORY_CARDS))  # fmt: skip
    return plan


def init_kaa(scenario, *, idol: str | None = None, battle_strategy: str = "bandai", require_sets: bool = True):
    """建 / 更新 KAA 培育方案并初始化 KAA 上下文。require_sets（new 开局）时 HIRO_SUPPORT_SET / HIRO_MEMORY_SET 必须给。"""
    from kaa.config.produce import ProduceSolutionManager
    from kaa.config.schema import KaaConfig
    from kaa.kaa_context import init as kaa_init

    apply_formation_plan(idol)
    missing = [n for n, v in (("HIRO_SUPPORT_SET", SUPPORT_SET), ("HIRO_MEMORY_SET", MEMORY_SET)) if v is None]
    if require_sets and missing:
        raise SetupMissing(f"开局需要编成号：请设 {' / '.join(missing)}（游戏里编好的编成号；确实想用おまかせ写 auto），"
                           "或先用 python -m hiro.brain.formation_plan 生成开局编成方案")  # fmt: skip
    manager = ProduceSolutionManager()
    solution = next((s for s in manager.list() if s.name == SOLUTION_NAME), None) or manager.new(SOLUTION_NAME)
    solution.data.mode = scenario
    solution.data.idol = idol
    solution.data.battle_strategy = battle_strategy
    solution.data.skip_commu = True
    if MEMORY_SET is not None:
        solution.data.auto_set_memory = MEMORY_SET == AUTO
        if MEMORY_SET != AUTO:
            solution.data.memory_set = MEMORY_SET
    if SUPPORT_SET is not None:
        solution.data.auto_set_support_card = SUPPORT_SET == AUTO
        if SUPPORT_SET != AUTO:
            solution.data.support_card_set = SUPPORT_SET
    manager.save(solution.id, solution)

    config = KaaConfig()
    config.tasks.produce.enabled = True
    config.tasks.produce.produce_count = 1
    config.tasks.produce.selected_solution_id = solution.id
    kaa_init(config, PROFILE_NAME)
    return config
