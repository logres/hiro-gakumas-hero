# 来源：digital-hiro hiro/recorder.py（c3fc27f）
"""一局培育的决策记录：每个决策点的截图、结构化状态、候选与选择，写入 reports/runs/<时间>/。

这份记录既是后续 LLM 决策的输入样本，也是视频后期的素材时间轴。
"""

import json
import time
from datetime import datetime
from pathlib import Path

import cv2
from cv2.typing import MatLike


class Recorder:
    def __init__(self, root: Path = Path("reports/runs")):
        self.dir = root / datetime.now().strftime("%Y%m%d-%H%M%S")
        (self.dir / "frames").mkdir(parents=True, exist_ok=True)
        self._events = (self.dir / "events.jsonl").open("a", encoding="utf-8")
        self._seq = 0

    def log(self, kind: str, *, image: MatLike | None = None, lossless: bool = False, **data) -> int:
        self._seq += 1
        frame = None
        if image is not None:
            frame = f"frames/{self._seq:05d}-{kind}.{'png' if lossless else 'jpg'}"
            cv2.imwrite(str(self.dir / frame), image, [] if lossless else [cv2.IMWRITE_JPEG_QUALITY, 85])
        row = {"seq": self._seq, "t": time.time(), "kind": kind, "frame": frame, **data}
        self._events.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        self._events.flush()
        return self._seq
