# 来源：digital-hiro src/hiro/vision/shop.py（develop c3fc27f）
# 部分逻辑基于 KAA（kotones-auto-assistant，GPL-3.0）的识别接口、主数据与界面模板
"""相談（CONSULT）货架：shelf / services / rerolls_left，格式按 docs/llm-context.md「商店字段」。

画面（720x1280）：上排 4 张技能卡、下排 4 瓶 P 饮料，每格 125x126，下方是价格条（SALE 时「原价 → 实付价」两个数）；
买过的格子盖着「交換済」；再往下是「強化 P100」「削除 P100」两个服务按钮和左下「あと N回 リフレッシュ」。
- 文字（价格、SALE、交換済、服务价格、刷新次数）：整块只做一次 Apple Vision，按坐标分到各格。
- 卡：KAA match_card_region（与三选一同一套卡面库）；强化看卡面右上角的红色「+」（有 100–143 像素，无 0）。
- 饮料：素材包 P 饮料图标库；货架图标约 102 像素，缩到 56 后在 ±6 像素内找最高分，附置信度，
  低于 DRINK_MIN 或领先次佳不足 DRINK_MARGIN 时 drink_id 为 None。
价格一律是画面上的实付价；读不到给 None。
complete：货架下方的说明行可见（没有获得动画 / 详情弹窗盖着）；为 False 时各格可能被遮挡或压暗，决策应等下一帧。
"""

import os
import re
from functools import cache
from pathlib import Path

import cv2
import numpy as np
from cv2.typing import MatLike

from hiro.vision.items import _library
from hiro.vision.ocr import ocr, ocr_boxes
from hiro.vision.digits import read_dddd

REGION = (40, 470, 700, 1070)
COLS = (65, 220, 375, 530)  # 各列格子左缘
CELL = 125
CARD_Y, DRINK_Y = 482, 668  # 卡 / 饮料格上缘
PRICE_BAND = {CARD_Y: (612, 652), DRINK_Y: (798, 838)}
SALE_BAND = {CARD_Y: (598, 624), DRINK_Y: (784, 810)}
SERVICE_BAND = (948, 992)
SERVICE_X = {"upgrade": (110, 330), "delete": (425, 645)}
REROLL_BAND = (1028, 1068)
HINT_BAND = (872, 926)  # 「持っているスキルカードの強化や削除ができます。」
PLUS_BOX = (30, 75, 88, 125)  # 卡格内红色「+」的位置 (y1, y2, x1, x2)
PLUS_MIN_PX = 40
DRINK_SIZE = 102  # 货架上饮料图标的显示尺寸
MATCH_SIZE = 56  # 缩到考试饮料栏同尺寸再比：分数 0.55–0.84、领先 0.2–0.7，比按原尺寸比快 20 倍且更稳
DRINK_MIN, DRINK_MARGIN = 0.45, 0.15
SERVICE_SAT_MIN = 50  # 服务按钮平均饱和度：强化（粉）70、削除（蓝）91；变灰时应明显更低（尚无样本）


def _red_plus(img: MatLike, x: int, y: int) -> tuple[int, int]:
    """卡格右上角红「+」的像素数：(严格阈值, 宽松阈值)。购买动画 / 弹窗把货架压暗时「+」变淡，只有宽松阈值数得到。
    严格阈值的红色块形状不像「+」（偶像插画里的红色，deck.plus_shape_ok）时严格计数记 0、宽松计数保留 → 上层给 None。"""
    from hiro.vision.deck import plus_shape_ok

    y1, y2, x1, x2 = PLUS_BOX
    hsv = cv2.cvtColor(img[y + y1 : y + y2, x + x1 : x + x2], cv2.COLOR_BGR2HSV)
    h, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    strict = ((h <= 12) | (h >= 170)) & (sat >= 140) & (val >= 150)
    loose = ((h <= 9) | (h >= 168)) & (sat >= 90) & (val >= 90)  # 「+」是纯红（色相 0–5）；≤14 会把橙色插画（思い出し笑い）算进来
    n_strict, n_loose = int(strict.sum()), int(loose.sum())
    if n_strict >= PLUS_MIN_PX and not plus_shape_ok(strict, CELL):
        return 0, max(n_loose, PLUS_MIN_PX)
    if n_strict < PLUS_MIN_PX and n_loose >= PLUS_MIN_PX and not plus_shape_ok(loose, CELL):
        return n_strict, 0  # 宽松阈值数到的是橙红插画（ゆるふわおしゃべり、思い出し笑い），形状不像「+」：当没有（第十七～十九局 チェンジ格 upgrade None）
    return n_strict, n_loose


def _card(img: MatLike, x: int, y: int = CARD_Y) -> dict:
    from kaa.game_ui.skill_card_select import match_card_region

    from hiro.vision.cards import card_version

    card = match_card_region(img[y : y + CELL, x : x + CELL])
    strict, loose = _red_plus(img, x, y)
    # 看得清有「+」→ 1；严格阈值没有、宽松阈值有（压暗的过渡帧）→ None（看不清，不冒充基础版）；都没有 → 0
    upgrade = 1 if strict >= PLUS_MIN_PX else (None if loose >= PLUS_MIN_PX else 0)
    if card is not None and upgrade:
        card = card_version(card._id, 1) or card
    return {"kind": "card", "card_id": card._id if card else None, "name": card.name if card else None, "upgrade": upgrade if card else None}


def _drink(img: MatLike, x: int, y: int = DRINK_Y) -> dict:
    from kaa.db.drink import Drink

    lib = _library("pdrink", MATCH_SIZE)
    cx, cy, h = x + CELL // 2, y + CELL // 2, DRINK_SIZE // 2
    crops = [cv2.resize(img[cy - h + dy : cy - h + dy + DRINK_SIZE, cx - h + dx : cx - h + dx + DRINK_SIZE], (MATCH_SIZE, MATCH_SIZE),
                        interpolation=cv2.INTER_AREA) for dx in (-6, 0, 6) for dy in (-6, 0, 6)]  # fmt: skip
    (score, asset), (second, _) = max(lib.match_many(crops), key=lambda t: t[0][0])
    ok = score >= DRINK_MIN and score - second >= DRINK_MARGIN
    drink = Drink.from_asset_id(asset) if ok else None
    return {"kind": "drink", "drink_id": drink.id if drink else None, "name": (lib.names.get(asset) or (drink.name if drink else None)) if ok else None,
            "confidence": round(score, 3), "margin": round(score - second, 3)}  # fmt: skip


def _nums(texts: list[str]) -> list[int]:
    return [int(n) for t in texts for n in re.findall(r"\d+", t.replace(",", ""))]


def _verified_price(img: MatLike, box: tuple[int, int, int, int]) -> int | None:
    """Exact numeric crop; all readers must agree, never repair from a price list."""
    x1, y1, x2, y2 = box
    crop = img[y1:y2, x1:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)[1]
    padded = cv2.copyMakeBorder(binary, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
    prepared = cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)
    values = [read_dddd(img, box)]  # exact bounds: no glyph-reader margin expansion
    for scale in (2, 4):
        tokens = ocr(prepared, scale=scale, languages=("en-US",))
        text = "".join(text for text, _ in tokens).strip()
        if not tokens or any(confidence < .9 for _, confidence in tokens) or not re.fullmatch(r"\d+", text):
            return None
        values.append(int(text))
    return values[0] if values[0] is not None and len(set(values)) == 1 else None


def _sale_mark(img: MatLike, x: int, top: int) -> bool:
    y1, y2 = SALE_BAND[top]
    hsv = cv2.cvtColor(img[y1:y2, x + 20:x + 110], cv2.COLOR_BGR2HSV)
    pink = ((hsv[:, :, 0] >= 160) | (hsv[:, :, 0] <= 5)) & (hsv[:, :, 1] >= 100) & (hsv[:, :, 2] >= 120)
    return int(pink.sum()) >= 100  # colored SALE pill; distinct from gray struck-through old price


def read_consult(img: MatLike) -> dict:
    """→ {"shelf": [{index, kind, card_id | drink_id, name, upgrade, price, sale, purchased, center}], "services": {...}, "rerolls_left"}。"""
    x0, y0, x1, y1 = REGION
    # 不去空格：SALE 的「75 52」会被 Vision 读成一个框，去空格就成了 7552
    boxes = [(t, (bx1 + x0, by1 + y0, bx2 + x0, by2 + y0)) for t, _, (bx1, by1, bx2, by2) in ocr_boxes(img[y0:y1, x0:x1], scale=2)]

    def texts_in(xr, yr) -> list[str]:
        return [t for t, (bx1, by1, bx2, by2) in boxes if xr[0] <= (bx1 + bx2) / 2 <= xr[1] and yr[0] <= (by1 + by2) / 2 <= yr[1]]

    shelf = []
    verify_price = os.environ.get("HIRO_WINDOWS_SHOP_PRICE_VERIFY") == "1"
    for row, top in ((0, CARD_Y), (1, DRINK_Y)):
        for col, x in enumerate(COLS):
            xr = (x - 10, x + CELL + 10)
            item = _card(img, x) if row == 0 else _drink(img, x)
            nums = _nums(texts_in(xr, PRICE_BAND[top]))
            sale = len(nums) >= 2 or any("SALE" in t.upper().replace(" ", "") for t in texts_in(xr, SALE_BAND[top]))
            if verify_price:
                # Do not infer SALE from fragmented digits of an ordinary price.
                sale = _sale_mark(img, x, top) or any("SALE" in t.upper().replace(" ", "") for t in texts_in(xr, SALE_BAND[top]))
            purchased = any("交換済" in t.replace(" ", "") for t in texts_in(xr, (top, top + CELL)))
            price = (_verified_price(img, (x + (76 if sale else 50), PRICE_BAND[top][0] + 10, x + 115, PRICE_BAND[top][0] + 36))
                     if verify_price else (nums[-1] if nums else None))
            shelf.append({"index": row * 4 + col, **item, "price": price, "sale": sale, "purchased": purchased,
                          "center": [x + CELL // 2, top + CELL // 2]})  # fmt: skip
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    services = {}
    for name, xr in SERVICE_X.items():
        nums = _nums(texts_in(xr, SERVICE_BAND))
        sat = float(hsv[SERVICE_BAND[0] : SERVICE_BAND[1], xr[0] : xr[1], 1].mean())
        price = (_verified_price(img, (xr[1] - 100, SERVICE_BAND[0] + 6, xr[1] - 10, SERVICE_BAND[1] - 4))
                 if verify_price else (nums[-1] if nums else None))
        services[name] = {"price": price, "available": sat >= SERVICE_SAT_MIN}
    m = re.search(r"あと\s*(\d+)\s*回", "".join(texts_in((40, 260), REROLL_BAND)))
    # 正常货架下方有一行「持っているスキルカードの強化や削除ができます。」；购买后的获得动画、卡牌详情弹窗会盖住它
    complete = any("強化や削除" in t.replace(" ", "") for t in texts_in((40, 700), HINT_BAND))
    # 说明行在、但货架被盖住（支援卡效果横幅「スキルカード強化時…」、强化 / 获得演出）：没买过的格子里 ≥2 格读不到价格或认不出物品就算不完整。
    # 第十二局 #234 横幅盖住第一行仍判完整，第 0 格读出幻影「アイドル宣言 4P」，决策去买、执行连失败 2 次。只差一格（新饮料认不出）不丢整个货架
    unread = [e["index"] for e in shelf if not e["purchased"] and (e["price"] is None or not (e.get("card_id") or e.get("drink_id")))]
    if len(unread) >= SHELF_UNREAD_MAX:
        complete = False
    return {"shelf": shelf, "services": services, "rerolls_left": int(m.group(1)) if m else None, "complete": complete}


SHELF_UNREAD_MAX = 2


# ---------------------------------------------------------------- 本战轮间（HIF_ROUND_INTERVAL）货架
# 第五局实机（reports/live/calib/20261031-2125*-轮间）：两行各 4 格，第 1 行后两格头上有「チェンジ」标签（セレクトチェンジ），
# 第 2 行后两格是饮料；下方「強化 P100 / 強化可能枚数あと N枚」「スキルカードカスタマイズ / カスタマイズ可能枚数あと N枚」「回復」（满体力变灰），
# 左下「リフレッシュ P10」。index 按位置从左上起 0–7：cards 0,1,4,5、changes 2,3、drinks 6,7（docs/llm-context.md「HIF_ROUND_INTERVAL」）。
INTERVAL_COLS = (55, 215, 375, 535)
INTERVAL_ROWS = (498, 692)  # 两行格子上缘
INTERVAL_PRICE = {498: (630, 670), 692: (824, 864)}
INTERVAL_KINDS = {0: "card", 1: "card", 2: "change", 3: "change", 4: "card", 5: "card", 6: "drink", 7: "drink"}
INTERVAL_REGION = (0, 300, 720, 1140)
INTERVAL_UPGRADE_BAND = (895, 960)
INTERVAL_COUNT_BAND = (965, 1000)
INTERVAL_RECOVER = (595, 900, 665, 975)  # 「回復」心形按钮：可用时白字白心，满体力时浅灰
RECOVER_WHITE_MIN = 200
INTERVAL_END_BAND = (1080, 1180)  # 底部「リフレッシュ / 交換する / 終了」：淡入帧还没有
INTERVAL_OPAQUE_SAT = 70  # 没买过的格子里最鲜艳一格的平均饱和度：正常 89，淡入半透明约 40
INTERVAL_REFRESH_BAND = (1080, 1130)
INTERVAL_REFRESH_LABEL_BAND = (1040, 1095)  # 「リフレッシュ」字样（第十七局 calib 172120 / 172458：y≈1070）
INTERVAL_HINT_BAND = (250, 330)  # 「Pポイントで利用するものを選んでください」
RECOVER_PRICE_PER_2HP = 10  # 体力回復確認：「体力を2回復」380 → 370


PURCHASED_MIN = 0.5  # 「交換済み」白字模板：买过 0.77–1.0，没买过 ≤ 0.21


@cache
def _purchased_tpl():
    tpl = cv2.imread(str(Path(__file__).with_name("templates") / "interval_purchased.png"))
    return cv2.inRange(cv2.cvtColor(tpl, cv2.COLOR_BGR2HSV), (0, 0, 215), (180, 50, 255))


def _purchased_mark(img: MatLike, x: int, top: int) -> bool:
    """格子上的「交換済み」白字（整帧 OCR 常漏：main8 R2 #97 / #100 / #101 第 4 格）。"""
    cell = cv2.inRange(cv2.cvtColor(img[top + 50 : top + 115, max(0, x - 5) : x + CELL + 5], cv2.COLOR_BGR2HSV), (0, 0, 215), (180, 50, 255))
    return float(cv2.matchTemplate(cell, _purchased_tpl(), cv2.TM_CCOEFF_NORMED).max()) >= PURCHASED_MIN


def _cell_sat(hsv, index: int) -> float:
    x, y = INTERVAL_COLS[index % 4], INTERVAL_ROWS[index // 4]
    return float(hsv[y : y + CELL, x : x + CELL, 1].mean())


def read_interval_shelf(img: MatLike) -> dict:
    """轮间货架 → {interval: {cards, changes, drinks, recover, upgrade, refresh, customize}, complete}。
    价格是画面实付价；读不到的项为 None。complete：货架上方的提示行可见（没有弹窗 / 动画盖住）。"""
    x0, y0, x1, y1 = INTERVAL_REGION
    boxes = [(t, (bx1 + x0, by1 + y0, bx2 + x0, by2 + y0)) for t, _, (bx1, by1, bx2, by2) in ocr_boxes(img[y0:y1, x0:x1], scale=2)]

    def texts_in(xr, yr) -> list[str]:
        return [t for t, (bx1, by1, bx2, by2) in boxes if xr[0] <= (bx1 + bx2) / 2 <= xr[1] and yr[0] <= (by1 + by2) / 2 <= yr[1]]

    out = {"cards": [], "changes": [], "drinks": []}
    for row, top in enumerate(INTERVAL_ROWS):
        for col, x in enumerate(INTERVAL_COLS):
            index = row * 4 + col
            kind = INTERVAL_KINDS[index]
            xr = (x - 10, x + CELL + 10)
            nums = _nums(texts_in(xr, INTERVAL_PRICE[top])) or _cell_price(img, x, INTERVAL_PRICE[top])
            purchased = any("交換済" in t.replace(" ", "") for t in texts_in(xr, (top, top + CELL))) or _purchased_mark(img, x, top)
            entry = {"index": index, "price": nums[-1] if nums else None, "purchased": purchased, "center": [x + CELL // 2, top + CELL // 2]}
            if kind == "drink":
                d = _drink(img, x, top)
                entry.update(drink_id=d["drink_id"], name=d["name"], confidence=d["confidence"])
                out["drinks"].append(entry)
            else:
                c = _card(img, x, top)
                entry.update(card_id=c["card_id"], name=c["name"], upgrade=c["upgrade"])
                out["cards" if kind == "card" else "changes"].append(entry)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    up = _nums(texts_in((40, 300), INTERVAL_UPGRADE_BAND))
    up_left = re.search(r"あと\s*(\d+)\s*枚", "".join(texts_in((40, 300), INTERVAL_COUNT_BAND)))
    cu_left = re.search(r"あと\s*(\d+)\s*枚", "".join(texts_in((300, 580), INTERVAL_COUNT_BAND)))
    # 可用时心形与「回復」是纯白（约 612 像素），满体力不可用时变浅灰（0）；绿色底两种状态饱和度差不多，分不开
    rx1, ry1, rx2, ry2 = INTERVAL_RECOVER
    btn = hsv[ry1:ry2, rx1:rx2]
    recover_ok = int(((btn[:, :, 1] < 30) & (btn[:, :, 2] > 235)).sum()) >= RECOVER_WHITE_MIN
    refresh = _nums(texts_in((20, 200), INTERVAL_REFRESH_BAND))
    upgrade_left = int(up_left.group(1)) if up_left else None
    out["upgrade"] = {"price": up[-1] if up else None, "available": (upgrade_left > 0) if upgrade_left is not None else None, "left": upgrade_left}
    out["customize"] = {"left": int(cu_left.group(1)) if cu_left else None}
    out["recover"] = {"available": recover_ok, "price_per_2hp": RECOVER_PRICE_PER_2HP}
    # 「リフレッシュ」按钮（左下，y≈1070）认得出且读到价格才算可用；认不出给 None（不当作不可用）。次数上限 / 涨价离线帧里没有，等实拍补 left
    refresh_btn = any("リフレッシュ" in t for t in texts_in((0, 260), INTERVAL_REFRESH_LABEL_BAND))
    out["refresh"] = {"price": refresh[-1] if refresh else None, "available": True if refresh_btn and refresh else None}
    # 货架淡入时格子半透明（卡 / 饮料会读错、回复按钮读成灰）：要提示行可见、底部「終了」出现、且第一格不透明才算完整
    #（数据确认 github-2c：trace 00159、reports/runs/20261031-211113/00040 淡入帧曾判 complete=True）
    hint = any("Pポイントで利用する" in t.replace(" ", "") for t in texts_in((40, 700), INTERVAL_HINT_BAND))
    end_btn = any("終了" in t for t in texts_in((500, 720), INTERVAL_END_BAND))
    # 不透明度看没买过的格子里最鲜艳的一格：买过的格子是灰的（main8 R2 #98–#101 买了第 0 格后连续 4 帧 complete=False，
    # interval 给 None，reduce 留着旧货架，决策又去买第 0 格）
    sats = {e["index"]: _cell_sat(hsv, e["index"]) for k in ("cards", "changes", "drinks") for e in out[k]}
    fresh = [v for i, v in sats.items() if not any(e["index"] == i and e["purchased"] for k in ("cards", "changes", "drinks") for e in out[k])]
    opaque = max(fresh or list(sats.values())) >= INTERVAL_OPAQUE_SAT
    return {"interval": out, "complete": hint and end_btn and opaque}


def _cell_price(img: MatLike, x: int, band: tuple[int, int]) -> list[int]:
    """整块 OCR 漏掉某格价格（第五局格 5 隔帧为 None）时，单独把这格的价格条放大再读。"""
    y1, y2 = band
    crop = cv2.resize(img[y1:y2, x + 30 : x + CELL + 5], None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    return _nums([t for t, _, _ in ocr_boxes(crop)])
