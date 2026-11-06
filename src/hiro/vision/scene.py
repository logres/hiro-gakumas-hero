# 来源：digital-hiro src/hiro/vision/scene.py（develop c3fc27f）
# 部分逻辑基于 KAA（kotones-auto-assistant，GPL-3.0）的识别接口、主数据与界面模板
"""统一场景识别：判断当前截图属于哪个页面。

培育内复用 KAA 的 ProducePage 场景检测（24 种 SceneType），培育外复用 KAA 的首页/商店等检测。
所有识别都只读当前截图（kotonebot manual 截图模式下，R.*.exists() 读取最近一次 device.screenshot()）。
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass

from kaa.config.const import HifScenario
from kaa.kaa_context import init_produce_session, produce_session
from kaa.tasks import R
from kaa.tasks.actions.commu import is_at_commu
from kaa.tasks.actions.scenes import at_home
from kaa.tasks.produce.new.page import CardSelectContext, ProducePage
from kaa.tasks.produce.session import ProduceSession
from kotonebot.backend.context import device, get_context

from hiro.vision.deck import is_deck_list
from hiro.vision.drinks import read_drink_dialog
from hiro.vision.hif import is_hif_exam, is_hif_result
from hiro.vision.pages import acquire_over, classify_page
from hiro.vision.pitem_select import is_select_pitem
from hiro.vision.support import is_start_confirm
from hiro.vision.signature import match as signature_match

# 授業与おでかけ签名分不开；KAA优先，已选中导致IDLE时用标题+完整事件布局核对。
SIGNATURE_DEFER = {"OUTING", "STUDY"}
# 三选一的选卡 / 选饮料弹窗布局相同（受け取る、カード除去 椭圆按钮），SELECT_DRINK 签名是这些通用按钮，
# 选卡页会以 2/3 票判成 SELECT_DRINK（第四局 r3/r4 实机 3 帧）；而饮料满、已选中一瓶的差し入れ页 KAA 认不出，只能靠签名。
# 所以签名给出这两页时，按三个候选格像不像饮料图标再定（_card_or_drink）
CARD_OR_DRINK = {"SELECT_CARD", "SELECT_DRINK"}
ACQUIRE_OVER = {"CONSULT"}  # KAA 判出这些页面时，先看是否被获得演出盖住

# 剧情只看 SKIP/快进按钮（阈值 0.6），会把课程里的「跳过回合」按钮误判为剧情，所以排在培育场景之后



@dataclass
class SceneResult:
    area: str  # produce / outside / unknown
    scene: str
    elapsed_ms: float


def ensure_produce_session() -> None:
    """ProducePage 的部分检测按剧本区分；离线识别默认按 HIF 正赛。"""
    if produce_session() is None:
        init_produce_session(ProduceSession("", HifScenario.MAIN, True))


@contextmanager
def _no_input():
    """KAA 的场景检测并非只读：_check_action_like 遇到开局饮料/卡二选一时会直接 double_click。
    识别期间把设备的点击类方法替换为空操作，保证分类不改变游戏状态。"""
    ctx = get_context()
    dev = ctx.device if ctx is not None else None
    names = ("click", "double_click", "swipe", "long_press")
    saved = {n: dev.__dict__.get(n) for n in names} if dev is not None else {}
    try:
        for n in names:
            if dev is not None and hasattr(dev, n):
                setattr(dev, n, lambda *a, **k: None)
        yield
    finally:
        for n, v in saved.items():
            if v is None:
                dev.__dict__.pop(n, None)
            else:
                setattr(dev, n, v)


DRINK_DIALOG_MIN_SCORE = 0.6  # 饮料弹窗三格最高分实测 0.74；选卡弹窗用不到这条（先按卡判）


def _selecting_dialog(img) -> str | None:
    """三选一弹窗里已选中某一项时，顶部提示「受け取る…を選んでください」换成了该项详情，
    KAA 靠这行提示判断 SELECT_CARD / SELECT_DRINK，因此会落到 IDLE。
    底部「受け取る」按钮选中前后都在（全数据集只在这类弹窗出现），据此补判；卡还是饮料由能否读出卡牌决定。"""
    if not R.InProduce.AcquireBtnDisabled.exists():
        return None
    if CardSelectContext(ProducePage(), None).fetch_cards():
        return "SELECT_CARD"
    if max(d["score"] for d in read_drink_dialog(img)) >= DRINK_DIALOG_MIN_SCORE:
        return "SELECT_DRINK"
    return None


def _card_or_drink(img) -> str:
    """选卡 / 选饮料 / 换卡第 1 步弹窗（签名分不开）：KAA 提示文字「受け取るスキルカード / Pドリンクを選んでください」优先；
    选中一项后提示被详情替换时，用 KAA 的选卡识别（fetch_cards）：认得出卡就是选卡，否则是选饮料。
    饮料图标分数分不开（选卡页最高 0.70，选饮料页最低 0.55）。"""
    if R.InProduce.DialogCardChange1.TipText.exists():
        return "SKILL_CARD_CHANGE_1"  # 换卡第 1 步「チェンジするスキルカードを選択してください」，布局同三选一
    if R.InProduce.TextSkillCard.exists():
        return "SELECT_CARD"
    if R.InProduce.TextPDrink.exists():
        return "SELECT_DRINK"
    return "SELECT_CARD" if CardSelectContext(ProducePage(), None).fetch_cards() else "SELECT_DRINK"



def _selected_event(img) -> str | None:
    """Recover selected study/outing pages only with title AND event-layout evidence.

    A title alone (including an acquisition/log mentioning study) is insufficient.
    read_event_choices verifies the three row positions and unique saturated row;
    require all row texts plus the selected effect detail before dispatching.
    """
    import unicodedata
    from hiro.vision.ocr import ocr_boxes
    from hiro.vision.event import read_event_choices, ROW_Y

    if img.shape[:2] != (1280, 720):
        return None
    titles = {unicodedata.normalize("NFKC", "".join(t.split()))
              for t, score, _ in ocr_boxes(img[35:90, 30:195], scale=4)
              if score >= .85}
    matched = titles.intersection({"授業", "おでかけ"})
    if len(matched) != 1:
        return None
    fields = read_event_choices(img)
    choices, selected = fields.get("choices"), fields.get("selected")
    if (fields.get("complete") is not True or type(selected) is not int or selected not in range(3)
            or not isinstance(choices, list) or len(choices) != 3
            or not isinstance(fields.get("effect"), str) or len(fields["effect"].strip()) < 4):
        return None
    for index, choice in enumerate(choices):
        if (not isinstance(choice, dict) or choice.get("index") != index
                or not isinstance(choice.get("text"), str) or len(choice["text"].strip()) < 2
                or choice.get("center") != [360, ROW_Y[index]]
                or choice.get("selected") is not (index == selected)):
            return None
    return "STUDY" if matched == {"授業"} else "OUTING"


def _fallback(img) -> str | None:
    """KAA 判不出时的像素兜底。界面 Sprite（页面签名）是自建素材，开源默认没有：签名本来能认的几页在这里补上。
    - quick.fallback_page：选行动页（「P手帳」标签）、Pドリンク所持上限 列表；
    - 选饮料页饮料已满且选中了一瓶（KAA 的提示文字被详情替换）：「Pドリンク所持上限」红标。"""
    from hiro.vision.items import drink_full_badge
    from hiro.vision.quick import fallback_page

    fb = fallback_page(img)
    if fb is not None:
        return fb
    return "SELECT_DRINK" if drink_full_badge(img) else None


def classify_current() -> SceneResult:
    """对最近一次 device.screenshot() 的画面分类。"""
    ensure_produce_session()
    start = time.perf_counter()

    def done(area: str, scene: str) -> SceneResult:
        return SceneResult(area, scene, (time.perf_counter() - start) * 1000)

    with _no_input():
        img = device.screenshot()
        if is_hif_exam(img):
            return done("produce", "HIF_EXAM")
        if is_hif_result(img):
            return done("produce", "HIF_EXAM_RESULT")
        if is_select_pitem(img):
            return done("produce", "SELECT_PITEM")
        if is_start_confirm(img):
            return done("outside", "PRODUCE_START_CONFIRM")
        if is_deck_list(img):
            return done("produce", "DECK_LIST")
        # 页面签名（客户端 Sprite 小窗口匹配，约 10ms）命中则直接返回；未命中再走 KAA 的逐项检测（50–170ms）
        fast, _ = signature_match(img)
        if fast in CARD_OR_DRINK:
            fast = _card_or_drink(img)
        if fast is not None and fast not in SIGNATURE_DEFER:
            return done("produce", fast)
        if at_home():
            return done("outside", "home")
        scene = ProducePage().check_scene()
        if scene is not None and scene.type.name == "SELECT_PITEM":
            # H.I.F 的 P 道具选择页上面 is_select_pitem 已判过；到这里多半是行动记录（「Pアイテム…を獲得」字样，qualify7 实机）
            hit = classify_page(img)
            if hit is not None and hit[0] == "PRODUCE_LOG":
                return done("produce", "PRODUCE_LOG")
        if scene is None or scene.type.name == "IDLE":
            event = _selected_event(img)
            if event is not None:
                return done("produce", event)
            selecting = _selecting_dialog(img)
            if selecting is not None:
                return done("produce", selecting)
        if scene is None or scene.type.name == "IDLE":
            # KAA 认不出的 H.I.F 页面（弹窗、获得演出、考前说明、定制、菜单、过渡帧…）：docs/pages-hif.md
            hit = classify_page(img)
            if hit is not None:
                return done("outside" if hit[0] == "MENU" and hit[1].get("kind") == "home" else "produce", hit[0])
        if scene is not None and scene.type.name in ACQUIRE_OVER:
            # 相談购买后的获得演出盖在货架上，KAA 仍判 CONSULT（数据确认 00128–00137）：名称栏命中就判 ACQUIRE
            if acquire_over(img) is not None:
                return done("produce", "ACQUIRE")
        if scene is not None:
            return done("produce", scene.type.name)
        fb = _fallback(img)
        if fb is not None:
            return done("produce", fb)
        if is_at_commu():
            return done("outside", "commu")
        return done("unknown", "unknown")
