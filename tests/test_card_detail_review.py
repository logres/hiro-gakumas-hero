from types import SimpleNamespace

from hiro.exec.card_detail_review import review_exam_hand_details, image_sha256


class Image:
    def __init__(self, name):
        self.name = name

    def tobytes(self):
        return self.name.encode()


def run(*, missing_close=False, changed=False, mismatch=False, duplicate=False):
    current = Image("exam")
    taps = []
    hand = [SimpleNamespace(slot=0, card_id="a", upgrade=1),
            SimpleNamespace(slot=1, card_id="a" if duplicate else "b", upgrade=1)]
    cells = [dict(index=0, card_id="b", upgrade=1, center=(10, 10)),
             dict(index=1, card_id="a", upgrade=1, center=(20, 20))]

    def click(point):
        nonlocal current
        taps.append(point)
        current = Image({(1, 1): "modal", (10, 10): "b", (20, 20): "a", (9, 9): "changed" if changed else "exam"}[point])

    def read(image):
        active = image.name not in ("exam", "changed")
        chosen = next((c for c in cells if c["card_id"] == image.name), None)
        identity = {"card_id": "wrong" if mismatch else image.name, "upgrade": 1}
        return dict(active=active, layout_complete=active, hand_count=2, cards=cells,
                    selected=chosen["index"] if chosen else None, selected_card=identity,
                    detail=identity, agree=True, detail_lines=[{"text": "元気+7"}])

    initial = current
    result = review_exam_hand_details(initial, hand, shoot=lambda: current, click=click,
        sleep=lambda _: None, same_state=lambda im: im.name == "exam",
        read_details=read, find_button=lambda _: (1, 1),
        close_buttons=lambda _: [] if missing_close else [(9, 9)], max_polls=2)
    return result, taps, initial


def test_identity_match_ignores_list_order_and_binds_snapshot():
    result, taps, initial = run()
    assert result.restored
    assert taps == [(1, 1), (20, 20), (10, 10), (9, 9)]
    assert [e["card_id"] for e in result.evidence] == ["a", "b"]
    assert all(e["snapshot_sha256"] == image_sha256(initial) for e in result.evidence)


def test_missing_close_stops_and_discards_evidence():
    result, taps, _ = run(missing_close=True)
    assert not result.restored and not result.evidence
    assert taps.count((1, 1)) == 1
    assert "close_button_not_unique" in result.problems


def test_changed_state_discards_evidence():
    result, _, _ = run(changed=True)
    assert not result.restored and not result.evidence


def test_mismatched_detail_closes_without_evidence():
    result, taps, _ = run(mismatch=True)
    assert result.restored and not result.evidence
    assert taps == [(1, 1), (20, 20), (9, 9)]


def test_duplicate_copies_are_never_assigned_to_slots():
    result, taps, _ = run(duplicate=True)
    assert result.restored and not result.evidence
    assert taps == [(1, 1), (9, 9)]


def test_changed_fresh_frame_prevents_opening():
    taps = []
    initial, fresh = Image("exam"), Image("changed")
    result = review_exam_hand_details(initial, [], shoot=lambda: fresh,
        click=taps.append, sleep=lambda _: None,
        same_state=lambda image: image.name == "exam",
        read_details=lambda _: {}, find_button=lambda _: (1, 1))
    assert not result.restored and not result.evidence and not taps


def test_open_button_is_recognized_on_fresh_frame():
    initial, fresh = Image("old"), Image("fresh")
    seen = []
    result = review_exam_hand_details(initial, [], shoot=lambda: fresh,
        click=lambda _: None, sleep=lambda _: None,
        same_state=lambda _: True, read_details=lambda _: {},
        find_button=lambda image: seen.append(image) or None)
    assert result.restored and seen == [fresh]
