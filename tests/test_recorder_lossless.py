import hashlib
import json

import cv2
import numpy as np
import pytest

from hiro.recorder import Recorder

pytestmark = pytest.mark.synthetic


def test_opt_in_diagnostic_frame_preserves_pixels_and_default_stays_jpeg(tmp_path):
    image = np.random.default_rng(41).integers(0, 256, (32, 48, 3), dtype=np.uint8)
    digest = hashlib.sha256(image.tobytes()).hexdigest()
    recorder = Recorder(tmp_path)
    try:
        recorder.log("ordinary", image=image)
        recorder.log("exam_card_detail_rejected", image=image, lossless=True, pixel_sha256=digest)
        rows = [json.loads(line) for line in (recorder.dir / "events.jsonl").read_text(encoding="utf8").splitlines()]
        assert rows[0]["frame"].endswith(".jpg")
        assert rows[1]["frame"].endswith(".png")
        restored = cv2.imread(str(recorder.dir / rows[1]["frame"]))
        assert np.array_equal(image, restored)
        assert hashlib.sha256(restored.tobytes()).hexdigest() == rows[1]["pixel_sha256"]
    finally:
        recorder._events.close()
