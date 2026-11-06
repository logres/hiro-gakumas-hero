# 来源：digital-hiro src/hiro/vision/status.py（develop c3fc27f）；开源版改：游戏素材经插件 AssetSource（hiro.vision.assets），拿不到时退路见各处注释
# 部分逻辑基于 KAA（kotones-auto-assistant，GPL-3.0）的识别接口、主数据与界面模板
"""考试画面左侧状态栏：逐个槽位识别状态效果与卡牌持续效果。

状态栏是固定间距的竖排菱形（720x1280 下槽中心 y = 262 + 61k，x = 44），从上往下连续排列：
- 蓝底白图案：考试状态效果（やる気、好印象、好調……）。图案与游戏资源包里的 93 个
  img_general_icon_exam-effect_* 图标（识别素材包 icons/exam_effect）按白色字形做多尺度相关。
- 其他底色：卡牌打出后留下的持续效果（如デイドリーミング「4ターン」、エウレカ！常驻），
  菱形里是来源卡的卡面局部，与技能卡图库的中心区域做灰度相关。
右下角的数值（18、20%、4ターン）用 Apple Vision 读。
"""

import json
import re
from functools import lru_cache

import cv2
import numpy as np
from cv2.typing import MatLike
from kaa.db.skill_card import SkillCard

from hiro.vision import assets
from hiro.vision.region_cache import RegionCache, cached
from hiro.vision import layout
from hiro.vision.digits import read_dddd, read_leading_int
from hiro.vision.ocr import ocr

ICON_PREFIX = "img_general_icon_exam-effect_"
_FIRST_SLOT = "BuffListRoot/BuffList/ExamMainBuffView"
# 槽位几何取自客户端布局：首槽菱形中心（截图校准），间距为槽高（布局给出 61.3）
SLOT_X, SLOT_Y0 = (round(v) for v in layout.center(layout.EXAM, _FIRST_SLOT))
_x, _y, _w, _h = layout.node(layout.EXAM, _FIRST_SLOT)[1]["rect"]
SLOT_PITCH, SLOT_HALF = _h, 28
MAX_SLOTS = 10
BLUE = ((95, 120, 150), (110, 255, 255))
BLUE_MIN_RATIO = 0.08  # 槽内蓝底像素占比：状态效果实测 0.19–0.32，卡牌效果为 0
GLYPH_SIZES = (30, 34, 38, 42)
PRERANK_SIZE = 2  # 粗排用的尺寸（38）
PRERANK_KEEP = 16
STATUS_MIN_SCORE = 0.6
# 使用者自建的图标（tools/assets/capture_icons.py，index.json 里 source=capture）：图库往往只有几个，没收进来的图标会被
# 「最像的那个」顶上（パラメータ上昇量増加 的上箭头配到 好印象 0.68）。实测同一图标 ≥ 0.725、领先 ≥ 0.15；不同图标 ≤ 0.70、领先 ≤ 0.09
CAPTURED_MIN_SCORE, CAPTURED_MIN_MARGIN = 0.72, 0.12
ENCHANT_MIN_SCORE = 0.6
CARD_INNER = 24  # 卡面比对的缩放边长


def _slot_y(k: int) -> int:
    return round(SLOT_Y0 + SLOT_PITCH * k)


def _slot(img: MatLike, k: int, half: int = SLOT_HALF, dy: int = 0) -> MatLike:
    cy = _slot_y(k) + dy
    return img[cy - half : cy + half, SLOT_X - half : SLOT_X + half]


AMBIGUOUS_MARGIN = 0.02  # 合成自测：不同图标在游戏尺寸下最近的一对（buffconsumption add/down）分差 < 0.01


@lru_cache(maxsize=1)
def _icon_index() -> tuple[dict, dict[str, list[np.ndarray]]]:
    """图标键 → 多尺度字形模板。资源里有完全相同的图标（如 examfullpowerpoint / examfullpowerpointreduce），
    只保留一份模板，其余记入 meta[键]["aliases"]，识别时一并给出。"""
    icons = assets.icon_dir("status")
    if icons is None:
        return {}, {}  # 没有考试效果图标：状态名给 None，只读数值
    index = icons / "index.json"
    meta = json.loads(index.read_text()) if index.exists() else {}
    templates, seen = {}, {}
    for png in sorted(icons.glob("*.png")):
        alpha = cv2.imread(str(png), cv2.IMREAD_UNCHANGED)[:, :, 3]
        key = png.stem.removeprefix(ICON_PREFIX)
        digest = alpha.tobytes()
        if digest in seen:
            meta.setdefault(seen[digest], {}).setdefault("aliases", []).append(key)
            continue
        seen[digest] = key
        templates[key] = [cv2.resize(alpha, (s, s), interpolation=cv2.INTER_AREA).astype(np.float32) for s in GLYPH_SIZES]
    return meta, templates


def _glyph(patch: MatLike) -> np.ndarray:
    return cv2.inRange(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV), (0, 0, 215), (180, 70, 255)).astype(np.float32)


def match_status_icon(patch: MatLike) -> list[tuple[float, str]]:
    """蓝底槽 → [(分数, 图标键)]，按分数降序取前 3。"""
    _, templates = _icon_index()
    if not templates:
        return [(0.0, ""), (0.0, "")]  # 没有考试效果图标：0 分占位（低于 STATUS_MIN_SCORE），状态名给 None
    g = _glyph(patch)

    def score(t: np.ndarray) -> float:
        if t.shape[0] > g.shape[0] or t.shape[1] > g.shape[1]:
            return 0.0
        return float(cv2.minMaxLoc(cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED))[1])

    # 先用一个尺寸粗排，只对前 PRERANK_KEEP 名试全部尺寸（matchTemplate 372 次 → 约 160 次）。
    # 数据集 179 个槽位上，得分 ≥ 0.6 的槽第一名与逐个全尺寸比对完全一致
    pre = sorted(((score(sizes[PRERANK_SIZE]), key) for key, sizes in templates.items()), reverse=True)[:PRERANK_KEEP]
    scored = sorted(((max(score(t) for t in templates[key]), key) for _, key in pre), reverse=True)
    return scored[:3]


def _norm(gray: np.ndarray) -> np.ndarray:
    g = gray.astype(np.float32)
    g -= g.mean()
    return (g / (np.linalg.norm(g) + 1e-6)).ravel()


def _inner(bgr: MatLike) -> np.ndarray:
    """菱形内接正方形（边长约为菱形外框的一半），灰度缩到固定大小。"""
    h, w = bgr.shape[:2]
    r = h // 4
    sq = bgr[h // 2 - r : h // 2 + r, w // 2 - r : w // 2 + r]
    return cv2.resize(cv2.cvtColor(sq, cv2.COLOR_BGR2GRAY), (CARD_INNER, CARD_INNER), interpolation=cv2.INTER_AREA)


@lru_cache(maxsize=1)
def _card_index() -> tuple[list[str], np.ndarray]:
    folder = assets.card_art_dir()
    if folder is None:
        return [], np.zeros((0, 1), np.float32)
    keys, rows = [], []
    for png in sorted(folder.glob("*.png")):
        im = cv2.imread(str(png))
        if im is None:
            continue
        h, w = im.shape[:2]
        s = min(h, w)
        keys.append(png.stem)
        rows.append(_norm(_inner(im[(h - s) // 2 : (h + s) // 2, (w - s) // 2 : (w + s) // 2])))
    return keys, np.stack(rows)


def match_enchant_card(img: MatLike, k: int) -> tuple[float, str]:
    """非蓝槽 → (分数, 卡面资源名)。菱形大小与位置有几像素浮动，小范围搜索取最高。"""
    keys, matrix = _card_index()
    if not keys:
        return 0.0, ""
    vecs = np.stack([_norm(_inner(_slot(img, k, half, dy))) for half in (24, 26, 28) for dy in (-3, 0, 3)], axis=1)
    scores = matrix @ vecs  # 卡数×9：一次矩阵乘代替 9 次矩阵乘向量
    i, j = np.unravel_index(int(scores.argmax()), scores.shape)
    return float(scores[i, j]), keys[i]


def _card_from_asset(key: str) -> SkillCard | None:
    base = "-".join(key.removeprefix("img_general_skillcard_").split("-")[:2])
    return SkillCard.from_asset_id("img_general_skillcard_" + base) or SkillCard.from_asset_id(key)


# 槽位存在性：菱形四条斜边上都有清晰边缘。只看左上/右上/左下三条（右下角有数值文字），取覆盖率最低的一条。
# 实测真实槽位 ≥ 0.92，空槽（地面、头发、白色台阶等背景）≤ 0.78。
DIAMOND_HALF = 32
DIAMOND_MIN = 0.85
_yy, _xx = np.mgrid[-DIAMOND_HALF:DIAMOND_HALF, -DIAMOND_HALF:DIAMOND_HALF] + 0.5
_DIST = np.abs(_xx) + np.abs(_yy)
_SIDES = [(_xx < 0) & (_yy < 0), (_xx > 0) & (_yy < 0), (_xx < 0) & (_yy > 0)]


def diamond_score_at(img: MatLike, cx: int, cy: int) -> tuple[float, int]:
    """以 (cx, cy) 为中心的菱形边缘得分，及最佳半径（中心到顶点的距离）。"""
    h = DIAMOND_HALF
    patch = img[cy - h : cy + h, cx - h : cx + h]
    if patch.shape[:2] != (2 * h, 2 * h):
        return 0.0, 0
    edges = cv2.dilate(cv2.Canny(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), 40, 120), np.ones((3, 3), np.uint8)) > 0
    best = (0.0, 0)
    for r in range(22, 31):
        ring = np.abs(_DIST - r) <= 0.8
        best = max(best, (min(float(edges[ring & side].mean()) for side in _SIDES), r))
    return best


def diamond_score(img: MatLike, k: int) -> float:
    return diamond_score_at(img, SLOT_X, _slot_y(k))[0]


UNITS = ("%", "ターン", "回")
ICON_GLYPH_HALF = 20  # 菱形内白色图案的半径（菱形外框约 27，数字左缘离中心约 18）


_ENCHANT_UNIT: dict[str, str | None] = {}  # 卡牌持续效果的单位（ターン / 回）由卡决定：每张卡只用 OCR 读一次


def _masked_region(img: MatLike, k: int) -> tuple[MatLike, int, int]:
    """数值附近一小块，菱形图标内部涂黑：图标里的白色图案（やる気的拳头、好印象的拇指）紧挨着数字，
    会被当成「被特效遮住的字」，让整串判为不确定。"""
    cy = _slot_y(k)
    x0, y0 = SLOT_X - 40, cy - 30
    region = img[y0 : cy + 50, x0 : SLOT_X + 140].copy()
    r = ICON_GLYPH_HALF
    cv2.fillConvexPoly(region, np.array([[40, 30 - r], [40 + r, 30], [40, 30 + r], [40 - r, 30]], np.int32), (0, 0, 0))
    return region, x0, y0


def _unit_label(img: MatLike, k: int) -> str | None:
    cy = _slot_y(k)
    label = "".join(t for t, _ in ocr(img[cy - 2 : cy + 34, SLOT_X + 14 : SLOT_X + 130])).replace(" ", "")
    return next((u for u in UNITS if u in label), None)


def _value(img: MatLike, k: int, kind: str, card_id: str | None = None) -> tuple[int | None, str | None]:
    """数值用游戏字体比对，「%」由紧跟数字的小圈认出；卡牌效果槽的「ターン / 回」按卡缓存，首次用 Apple Vision 读。
    字体比对没把握时（数字被特效遮住、状态槽数字后跟着认不出的字）退回 ddddocr + Apple Vision。"""
    cy = _slot_y(k)
    region, x0, y0 = _masked_region(img, k)
    value, suffix = read_leading_int(region, (SLOT_X + 12 - x0, cy + 2 - y0, SLOT_X + 60 - x0, cy + 32 - y0))
    if value is None and suffix == "empty":
        return None, None  # 常驻效果（エウレカ！等）不显示数值
    if value is not None and suffix in (None, "%"):
        return value, suffix
    if value is not None and kind == "enchant":
        if card_id is None:
            return value, _unit_label(img, k)
        if _ENCHANT_UNIT.get(card_id) is None:
            unit = _unit_label(img, k)
            if unit is None:
                return value, None  # 这次没读到（被特效遮住等）：不缓存，下次再读
            _ENCHANT_UNIT[card_id] = unit
        return value, _ENCHANT_UNIT[card_id]
    # 慢路径：与原实现相同
    value = read_dddd(img, (SLOT_X + 12, cy + 2, SLOT_X + 60, cy + 32))
    if value is None:
        return None, None
    return value, _unit_label(img, k)


def read_status_column(img: MatLike, *, cache: RegionCache | None = None) -> list[dict]:
    """检查全部槽位；后方仍有图标的低分槽保持未知，不能截断状态列。

    Trailing empty slots are omitted. An uncertain outline before a detected
    slot is not evidence of absence, even when every readable icon is known.
    """
    scores = [diamond_score(img, k) for k in range(MAX_SLOTS)]
    occupied = [k for k, score in enumerate(scores) if score >= DIAMOND_MIN]
    if not occupied:
        return []
    out = []
    for k in range(occupied[-1] + 1):
        if scores[k] < DIAMOND_MIN:
            out.append({"slot": k, "kind": "status", "key": None,
                        "value": None, "score": round(scores[k], 3),
                        "uncertain": "slot_outline"})
            continue
        cy = _slot_y(k)
        region = img[cy - SLOT_HALF - 4 : cy + 36, SLOT_X - SLOT_HALF - 4 : SLOT_X + 130]
        out.append(cached(cache, f"status{k}", region, lambda k=k: _read_slot(img, k)))
    return out


def _accepted(meta: dict, top: list[tuple[float, str]]) -> bool:
    """图标匹配结果可信：分数够；第一名是自建图标时另要更高的分数与领先（见 CAPTURED_MIN_SCORE）。"""
    score, key = top[0]
    if score < STATUS_MIN_SCORE:
        return False
    if meta.get(key, {}).get("source") == "capture":
        return score >= CAPTURED_MIN_SCORE and score - top[1][0] >= CAPTURED_MIN_MARGIN
    return True


def _read_slot(img: MatLike, k: int) -> dict:
    meta, _ = _icon_index()
    patch = _slot(img, k)
    blue = cv2.inRange(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV), *BLUE)
    if np.count_nonzero(blue) / blue.size >= BLUE_MIN_RATIO:
        top = match_status_icon(patch)
        score, key = top[0]
        if not _accepted(meta, top):
            entry = {"slot": k, "kind": "status", "key": None, "score": round(score, 3), "candidates": [c for _, c in top]}
        else:
            info = meta.get(key, {})
            entry = {"slot": k, "kind": "status", "key": key, "type": info.get("type"), "name": info.get("name"),
                     "score": round(score, 3), "margin": round(score - top[1][0], 3)}  # fmt: skip
            # 图标相同或几乎相同的类型无法只凭图标区分，列出全部候选交给状态机按上下文判断
            alternatives = info.get("aliases", []) + [c for s2, c in top[1:] if score - s2 < AMBIGUOUS_MARGIN]
            if alternatives:
                entry["alternatives"] = alternatives
    else:
        score, asset = match_enchant_card(img, k)
        card = _card_from_asset(asset) if score >= ENCHANT_MIN_SCORE else None
        grey = None if card is not None else match_status_icon(patch)
        if grey and _accepted(meta, grey):
            # 培育计划的核心状态（やる気 等）为 0 时以灰底常驻、不显示数值；卡面认不出而字形能认出即是这种槽
            gscore, key = grey[0]
            info = meta.get(key, {})
            return {"slot": k, "kind": "status", "key": key, "type": info.get("type"), "name": info.get("name"),
                    "score": round(gscore, 3), "margin": round(gscore - grey[1][0], 3), "inactive": True, "value": 0, "unit": None}  # fmt: skip
        entry = {"slot": k, "kind": "enchant", "card_id": card._id if card else None,
                 "name": card.name if card else None, "asset": asset, "score": round(score, 3)}  # fmt: skip
    entry["value"], entry["unit"] = _value(img, k, entry["kind"], entry.get("card_id"))
    return entry


def status_summary(entries: list[dict]) -> dict:
    """{图标键: 数值}，方便按类型取值（如 examcardplayaggressive=やる気、examreview=好印象）。"""
    return {e["key"]: e.get("value") for e in entries if e["kind"] == "status" and e.get("key")}
