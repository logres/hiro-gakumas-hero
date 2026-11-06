"""Read actual next-level customization previews without committing a purchase."""
from dataclasses import dataclass
import numpy as np


@dataclass
class MenuPreview:
    fields: dict
    image: np.ndarray


def _identity(fields):
    card = fields.get("selected_card") or {}
    if not card.get("card_id") or type(card.get("upgrade")) is not int:
        raise ValueError("定制预览卡牌身份或版本未知")
    return card["card_id"], card["upgrade"]


def _menu(fields, identity, budget):
    if fields.get("view") != "menu" or _identity(fields) != identity:
        raise ValueError("定制菜单或当前卡牌已变化")
    if type(fields.get("produce_point")) is not int or fields["produce_point"] != budget:
        raise ValueError("定制预览期间余额未知或发生变化")
    menu = fields.get("menu") or {}
    if type(menu.get("total_left")) is not int or menu["total_left"] <= 0:
        raise ValueError("当前卡牌剩余定制次数未知或用尽")
    items = menu.get("items") or []
    indices = [i.get("item_index") for i in items]
    if not items or any(type(i) is not int or i not in (0, 1, 2) for i in indices) or len(set(indices)) != len(indices):
        raise ValueError("定制菜单物理列不明确")
    return menu


def collect_current_menu(*, shoot, read, click, wait):
    """Return stable image-backed options; never click Execute or a confirmation.

    Starts and remains in the currently open card menu. Unknown/unreadable options
    are not silently ranked. A failed selection stops without repeating the click.
    """
    image = shoot()
    fields = read(image)
    identity = _identity(fields)
    budget = fields.get("produce_point")
    menu = _menu(fields, identity, budget)
    targets = [(i["item_index"], i.get("price"), i.get("left")) for i in menu["items"]
               if i.get("available") is True and not i.get("maxed")]
    if not targets:
        raise ValueError("没有可查看的定制选项")
    results = []
    for index, price, left in targets:
        if type(price) is not int or price < 0 or type(left) is not int or left <= 0:
            raise ValueError("定制选项价格或次数未知")
        image = shoot()
        fields = read(image)
        menu = _menu(fields, identity, budget)
        target = next((i for i in menu["items"] if i["item_index"] == index), None)
        if not target or (target.get("price"), target.get("left")) != (price, left):
            raise ValueError("定制选项已变化")
        if not target.get("selected"):
            center = target.get("center")
            if not center or len(center) != 2 or not (30 <= center[0] <= 690 and 790 <= center[1] <= 920):
                raise ValueError("定制选项坐标不在菜单区")
            click(*center)
            wait(.7)
        first_image = shoot()
        first = read(first_image)
        _menu(first, identity, budget)
        wait(.4)
        image = shoot()
        fields = read(image)
        _menu(fields, identity, budget)
        for observed in (first, fields):
            selected = [i for i in observed["menu"]["items"] if i.get("selected")]
            if (len(selected) != 1 or selected[0]["item_index"] != index
                    or observed["menu"].get("selected_item_index") != index):
                raise ValueError("定制选项单击后未确认选中，不重复点击")
            if (selected[0].get("price"), selected[0].get("left")) != (price, left):
                raise ValueError("定制预览价格或次数变化")
        # Compare only the effect panels, excluding animated HUD/background.
        a, b = first_image[158:743, 20:700], image[158:743, 20:700]
        if a.shape != b.shape or not a.size or np.abs(a.astype(float)-b.astype(float)).mean() > 3:
            raise ValueError("定制效果预览尚未稳定")
        results.append(MenuPreview(fields, image.copy()))
    return results
