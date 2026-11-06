from types import SimpleNamespace

import numpy as np
import pytest

from hiro.exec import exam
from hiro.exec import card_detail_review as review


@pytest.mark.parametrize("restored", [True, False])
def test_detail_inspection_restoration_gates_decision_context(monkeypatch, restored):
    monkeypatch.setenv("HIRO_EXAM_CARD_DETAILS", "1")
    image = np.zeros((2, 2, 3), dtype=np.uint8)
    identity = {"slot": 2, "card_id": "generic-card", "upgrade": 1}
    hand = [SimpleNamespace(**identity)]
    token = review.image_sha256(image)
    evidence = [{**identity, "selected_card": identity, "detail_card": identity,
                 "selection_verified": True, "snapshot_sha256": token,
                 "raw_ocr_lines": ["スキルカード使用数追加+1"]}]
    state = SimpleNamespace(hand=hand, public_info="catalog")
    events = []
    rec = SimpleNamespace(log=lambda kind, **kwargs: events.append((kind, kwargs)))
    globals_ = exam._review_current_card_details.__globals__
    monkeypatch.setitem(globals_, "_detail_state_facts", lambda img: {"hp": 20})
    monkeypatch.setitem(globals_, "device", SimpleNamespace(screenshot=lambda: image, click=lambda p: None))
    monkeypatch.setattr(review, "review_exam_hand_details", lambda *a, **kw:
                        review.ReviewResult(evidence, image, [], restored))
    if not restored:
        with pytest.raises(RuntimeError, match="no battle input"):
            exam._review_current_card_details(state, SimpleNamespace(img=image), rec)
        assert state.public_info == "catalog"
    else:
        exam._review_current_card_details(state, SimpleNamespace(img=image), rec)
        assert "スキルカード使用数追加+1" in state.public_info
        assert token in state.public_info
    assert events[-1][1]["restored"] is restored


def test_detail_inspection_disabled_by_default(monkeypatch):
    monkeypatch.delenv("HIRO_EXAM_CARD_DETAILS", raising=False)
    exam._review_current_card_details(None, None, None)
