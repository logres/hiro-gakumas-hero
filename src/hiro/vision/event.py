# 来源：digital-hiro src/hiro/vision/event.py（develop c3fc27f）
"""授業（STUDY）/ おでかけ（OUTING）三选一：选项文字、代价角标、选中项与选中后弹出的效果说明。

两页是同一套界面。三行选项中心 y ≈ 698 / 799 / 901（720x1280），每行右上方的角标是代价：
体力「-5」（心形）、P 点「P -50」或「トラブル追加」。选中一行后该行变成高饱和色并带「>>」，
上方弹出效果说明（「ボーカル上昇+120 / やる気関係のスキルカードを選択して獲得」）。
整块只做一次 Apple Vision，按文字框的 y 分到各行。
选中后其余两行会压暗，文字常丢首字：选项文字以未选状态那一帧为准，选中后主要读 selected 与 effect。
"""

import re
import unicodedata

import cv2
import numpy as np
from cv2.typing import MatLike

from hiro.vision.ocr import ocr_boxes

REGION = (75, 445, 720, 950)  # 四行效果框上移；左边界避开选项行首图标
ROW_Y = (698, 799, 901)
ROW_HALF = 26  # 选项文字行的半高
BADGE = (-56, -22)  # 角标相对行中心的 y 范围
TEXT_X = (70, 560)  # 选项文字的 x 范围（左边是图标，右边是「>>」）
BADGE_X = 520
EFFECT_Y = (445, 640)  # 三行/四行效果框，含四行框上移后的参数增益首行
SELECTED_SAT = 100  # 选中行饱和度：授業 118–166、外出 129–141；未选 ≤ 70
SELECTED_LEAD = 40


def _badge_kind(img: MatLike, x1: int, y1: int, y2: int) -> str | None:
    """角标数字左侧的小图标：黄 = P 点，绿 = 体力（取自 github-f4 的实现）。"""
    hsv = cv2.cvtColor(img[max(0, y1 - 4) : y2 + 4, max(0, x1 - 34) : max(1, x1 - 2)], cv2.COLOR_BGR2HSV)
    vivid = (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 120)
    if vivid.sum() < 15:
        return None
    hue = np.median(hsv[:, :, 0][vivid])
    if 15 <= hue <= 32:
        return "p"
    if 33 < hue <= 85:
        return "hp"
    return None


def _badge_fallback(img: MatLike, cy: int) -> tuple[int | None, int | None]:
    """整块识别漏掉的角标（选中后其余行压暗，小字常读不出）：单独裁按钮右上角放大再认。→ (体力消耗, P 消耗)。取自 github-f4。"""
    y1, y2 = cy + BADGE[0], cy + BADGE[1]
    for text, _, b in ocr_boxes(img[y1:y2, 560:700], scale=6, languages=("en-US",)):
        m = re.search(r"-?\s*(\d{1,3})", text)
        if not m:
            continue
        kind = _badge_kind(img, 560 + b[0], y1 + b[1], y1 + b[3])
        if kind is None and "-" not in text:
            continue
        value = int(m.group(1))
        return (None, value) if kind == "p" or "P" in text else (value, None)
    return None, None


def _row_of(cy: float, offset: tuple[int, int] = (-ROW_HALF, ROW_HALF)) -> int | None:
    for i, y in enumerate(ROW_Y):
        if y + offset[0] <= cy <= y + offset[1]:
            return i
    return None


def read_event_choices(img: MatLike) -> dict:
    """→ {"choices": [{index, text, cost_hp, cost_p, trouble, selected, center}], "selected": index | None, "effect": str | None, "complete": bool}。
    文字读不到的行 text 为 None；没有选中时 effect 为 None。"""
    x0, y0, x1, y1 = REGION
    boxes = [(t, (bx1 + x0, by1 + y0, bx2 + x0, by2 + y0)) for t, _, (bx1, by1, bx2, by2) in ocr_boxes(img[y0:y1, x0:x1], scale=2)]
    texts: list[list[tuple[int, str]]] = [[] for _ in ROW_Y]
    badges: list[list[tuple[str, tuple]]] = [[] for _ in ROW_Y]
    effect: list[tuple[int, str]] = []
    for t, (bx1, by1, bx2, by2) in boxes:
        cy = (by1 + by2) / 2
        if EFFECT_Y[0] <= cy <= EFFECT_Y[1] and _row_of(cy, BADGE) is None:
            effect.append((by1, t))
        elif (r := _row_of(cy)) is not None and bx1 < TEXT_X[1]:
            texts[r].append((bx1, t))
        elif (r := _row_of(cy, BADGE)) is not None and bx1 >= BADGE_X:
            badges[r].append((t, (bx1, by1, bx2, by2)))
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    sats = [float(hsv[y - 12 : y + 12, 120:520, 1].mean()) for y in ROW_Y]
    top = int(np.argmax(sats))
    selected = top if sats[top] >= SELECTED_SAT and all(sats[top] - s >= SELECTED_LEAD for i, s in enumerate(sats) if i != top) else None
    choices = []
    for i, y in enumerate(ROW_Y):
        text = "".join(t for _, t in sorted(texts[i])).strip()
        text = re.sub(r"^[\d\s>＞]+", "", text)  # 行首图标常被读成「2」
        text = re.sub(r"^\S\s+", "", text)  # 或读成单个符号 / 字加空格（「& 」「日 」）；选项文字本身不含空格
        text = re.sub(r"[>＞\s]+$", "", text) or None  # 选中行末尾的「>>」
        cost_hp = cost_p = None
        for t, (bx1, by1, _, by2) in badges[i]:
            m = re.search(r"-\s*(\d{1,3})", t) or re.fullmatch(r"\s*(\d{1,3})\s*", t)
            if not m:
                continue
            kind = _badge_kind(img, bx1, by1, by2)
            if "-" not in t and kind is None:
                continue  # 不带减号的数字只有左侧确有爱心 / P 图标时才算角标
            if kind == "p" or "P" in t or "Ｐ" in t:
                cost_p = int(m.group(1))
            else:
                cost_hp = int(m.group(1))
        trouble = any("トラブル" in t for t, _ in badges[i])
        if cost_hp is None and cost_p is None and not trouble:
            cost_hp, cost_p = _badge_fallback(img, y)
        choices.append({"index": i, "text": text, "cost_hp": cost_hp, "cost_p": cost_p, "trouble": trouble,
                        "selected": selected == i if selected is not None else False, "center": [360, y]})  # fmt: skip
    # 效果说明做 NFKC 规范化（全角「％」「＋」→ 半角），决策器按效果名匹配
    eff = unicodedata.normalize("NFKC", "\n".join(t for _, t in sorted(effect))) if selected is not None and effect else None
    # complete：三行选项文字都读到了（按钮滑入动画中的帧不完整，主循环会等下一帧）
    return {"choices": choices, "selected": selected, "effect": eff, "complete": all(c["text"] for c in choices)}
