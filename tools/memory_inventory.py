# 来源：digital-hiro tools/memory_inventory.py（1fc4d19）；调用 KAA / kotonebot（kotones-auto-assistant，GPL-3.0）
"""回忆库存扫描（回忆编成选择系统 §2）：在「メモリー選択」页逐格点回忆，读详情框两页，写 reports/live/memory-inventory.json。

只读：不点「決定」，结束时停在选择页（之后手动点キャンセル 退出）。实机运行时会连游戏操作。

用法：
  # 实机：先在编成页点一格回忆，进入メモリー選択（网格 + 上方详情框），再运行
  python tools/memory_inventory.py --live [--pages 12] [--out reports/live/memory-inventory.json]
  # 离线：用上次扫描的截图（reports/live/memscan-*.jpg 第 1 页、memscan2-*.jpg 第 2 页，360x640）生成样例
  python tools/memory_inventory.py --offline reports/live --out .temp/memory-inventory-offline.json

每份回忆一条：{index, page, cell, timing, card{card_id, name, upgrade}, plan, customized, card_text, ability, ability_truncated,
stats[{type, attr, value, active, truncated, text, …}], frames{p1, p2}, problems}。
上次扫描第 2 页有 7 处词条完全一样：点完格子后详情框还没刷新就截了图。这里每一步都等画面真的变了再读（见 _wait_change）。
HIRO_MEMORY_SCAN_VERIFIED=1：固定页码 OCR + 四角选中框 + 连续稳定帧；只扫两行完整卡格，任何过渡核实失败立即停止。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import time
from pathlib import Path

import cv2

GRID_X = (140, 360, 580)
GRID_Y = (647, 787, 920)  # 一屏完整可见的三行
PAGER_PREV, PAGER_NEXT = (233, 533), (484, 533)
SWIPE = (360, 960, 360, 560, 2.0)  # 约 3 行
WAIT_S, POLL_S = 4.0, 0.3


def _signature(rec: dict) -> tuple:
    card = rec.get("card") or {}
    stats = tuple((s.get("type"), s.get("attr"), s.get("value")) for s in rec.get("stats") or [])
    return card.get("card_id"), card.get("upgrade"), rec.get("timing"), rec.get("customized"), stats, rec.get("ability")


def offline(root: str) -> list[dict]:
    from hiro.vision.memory import merge_detail, read_memory_detail

    def load(p):
        return cv2.resize(cv2.imread(p), (720, 1280), interpolation=cv2.INTER_CUBIC)

    out = []
    for i, p in enumerate(sorted(glob.glob(os.path.join(root, "memscan-*.jpg")))):
        key = os.path.basename(p)[len("memscan-") :]
        p2 = os.path.join(root, "memscan2-" + key)
        d1 = read_memory_detail(load(p))
        d2 = read_memory_detail(load(p2)) if os.path.exists(p2) else None
        rec = {"index": i, "key": key, **merge_detail(d1 if d1 and d1["page"] == 1 else None, d2 if d2 and d2["page"] == 2 else None),
               "frames": {"p1": p, "p2": p2 if os.path.exists(p2) else None}}  # fmt: skip
        rec["problems"] = [f"缺 {k}" for k in ("card", "timing", "stats") if not rec.get(k)]
        out.append(rec)
    return out


class MemoryScanPending(RuntimeError):
    """The requested cell/page was not verified; stop without further input."""


def _wait_change(d, prev_texts: str | None, want_page: int | None, *, want_cell=None):
    """截图直到详情框文字与 prev 不同（且页码为 want_page）；超时返回最后一帧。"""
    from hiro.vision.memory import detail_page, picker_detail_open, verified_selected_cell
    from hiro.vision.pages import _texts

    verified = os.environ.get("HIRO_MEMORY_SCAN_VERIFIED") == "1"
    # Cold Windows OCR can spend the legacy four-second budget on its first
    # frame. Always permit the two observations required for stability.
    deadline = time.monotonic() + (12.0 if verified else WAIT_S)
    attempts = 0
    previous, stable = None, 0
    while True:
        img = d.screenshot()
        attempts += 1
        boxes = _texts(img)
        panel = "".join(t for t, b in boxes if 165 <= (b[1] + b[3]) // 2 <= 515)
        page = detail_page(boxes, img)
        if verified and not picker_detail_open(boxes):
            return img, boxes, panel, False
        correct = ((prev_texts is None or panel != prev_texts) and (want_page is None or page == want_page)
                   and (want_cell is None or verified_selected_cell(img) == want_cell))
        if correct:
            stable = stable + 1 if previous == (page, panel) else 1
            if not verified or stable >= 2:
                return img, boxes, panel, True
        else:
            stable = 0
        previous = (page, panel)
        if (time.monotonic() > deadline and (not verified or attempts >= 2)) or (verified and attempts >= 12):
            return img, boxes, panel, False
        time.sleep(POLL_S)


def _live_verified(d, pages: int, frames_dir: Path) -> list[dict]:
    """Fail closed on cell/page transitions; never click the covered third row."""
    from hiro.vision.memory import merge_detail, read_memory_detail

    def wait(page, cell=None, previous=None):
        frame = _wait_change(d, previous, page, want_cell=cell)
        if not frame[3]:
            raise MemoryScanPending(f"Memory picker cell {cell}, detail page {page} not verified; scanner stopped")
        return frame

    out, seen, previous_p1, previous_p2 = [], set(), None, None
    for page in range(pages):
        new_on_page = 0
        for r, y in enumerate(GRID_Y[:2]):
            for c, x in enumerate(GRID_X):
                wait(1)  # Verify the picker again before any cell input.
                d.click(x, y)
                img1, boxes1, panel1, _ = wait(1, (r, c), previous_p1)
                d1 = read_memory_detail(img1, boxes1)
                d.click(*PAGER_NEXT)
                img2, boxes2, panel2, _ = wait(2, (r, c), previous_p2)
                d2 = read_memory_detail(img2, boxes2)
                d.click(*PAGER_PREV)
                wait(1, (r, c))  # Complete the return before another cell click.
                previous_p1, previous_p2 = panel1, panel2
                rec = merge_detail(d1, d2)
                sig = _signature(rec)
                if sig in seen:
                    continue
                seen.add(sig)
                idx = len(out)
                f1, f2 = frames_dir / f"{idx:03d}-p1.jpg", frames_dir / f"{idx:03d}-p2.jpg"
                cv2.imwrite(str(f1), img1)
                cv2.imwrite(str(f2), img2)
                rec.update(index=idx, page=page, cell=[r, c], frames={"p1": str(f1), "p2": str(f2)},
                           problems=[f"缺 {k}" for k in ("card", "timing", "stats") if not rec.get(k)])
                out.append(rec)
                new_on_page += 1
                print(idx, page, r, c, (rec.get("card") or {}).get("name"), len(rec.get("stats") or []), flush=True)
        if not new_on_page or page + 1 == pages:
            break
        # Two complete rows per screen: scroll less than two rows, retaining overlap.
        d.swipe(360, 820, 360, 560, 1.0)
        time.sleep(1.5)
    return out


def live(pages: int, frames_dir: Path) -> list[dict]:
    from hiro.device import connect
    from hiro.vision.memory import merge_detail, read_memory_detail

    d = connect()
    frames_dir.mkdir(parents=True, exist_ok=True)
    if os.environ.get("HIRO_MEMORY_SCAN_VERIFIED") == "1":
        return _live_verified(d, pages, frames_dir)
    out, seen, prev_p1, prev_p2 = [], set(), None, None  # 上一份回忆两页的文字：新的一份两页都要和它不同才算刷新了
    for page in range(pages):
        new_on_page = 0
        for r, y in enumerate(GRID_Y):
            for c, x in enumerate(GRID_X):
                problems = []
                d.click(x, y)
                img1, boxes1, panel1, ok1 = _wait_change(d, prev_p1, 1)
                if not ok1:
                    problems.append("点格子后详情框没变（可能是同一份回忆，或没点中）")
                d1 = read_memory_detail(img1, boxes1)
                d.click(*PAGER_NEXT)
                img2, boxes2, panel2, ok2 = _wait_change(d, prev_p2, 2)
                if not ok2:
                    problems.append("翻到第 2 页超时")
                d2 = read_memory_detail(img2, boxes2)
                d.click(*PAGER_PREV)
                prev_p1, prev_p2 = panel1, panel2
                rec = merge_detail(d1 if d1 and d1["page"] == 1 else None, d2 if d2 and d2["page"] == 2 else None)
                sig = _signature(rec)
                if sig in seen:
                    continue  # 滑动有重叠：已经读过的行
                seen.add(sig)
                idx = len(out)
                f1, f2 = frames_dir / f"{idx:03d}-p1.jpg", frames_dir / f"{idx:03d}-p2.jpg"
                cv2.imwrite(str(f1), img1)
                cv2.imwrite(str(f2), img2)
                rec.update(index=idx, page=page, cell=[r, c], frames={"p1": str(f1), "p2": str(f2)},
                           problems=problems + [f"缺 {k}" for k in ("card", "timing", "stats") if not rec.get(k)])  # fmt: skip
                out.append(rec)
                new_on_page += 1
                print(idx, page, r, c, (rec.get("card") or {}).get("name"), rec.get("timing"), len(rec.get("stats") or []), problems, flush=True)
        if new_on_page == 0:
            break  # 滑不动了（到底）
        d.swipe(*SWIPE)
        time.sleep(1.5)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--live", action="store_true")
    g.add_argument("--offline", metavar="DIR")
    ap.add_argument("--pages", type=int, default=12)
    ap.add_argument("--out", default="reports/live/memory-inventory.json")
    ap.add_argument("--frames", default="reports/live/memory-inventory")
    a = ap.parse_args()
    import hiro  # noqa: F401

    recs = offline(a.offline) if a.offline else live(a.pages, Path(a.frames))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"generated": time.time(), "count": len(recs), "memories": recs}, ensure_ascii=False, indent=1))
    print("wrote", a.out, len(recs))


if __name__ == "__main__":
    main()
