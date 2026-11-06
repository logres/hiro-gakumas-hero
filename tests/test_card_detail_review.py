from types import SimpleNamespace
import pytest

from hiro.exec.card_detail_review import review_exam_hand_details, image_sha256


class Image:
    def __init__(self, name):
        self.name = name

    def tobytes(self):
        return self.name.encode()


def run(*, missing_close=False, changed=False, mismatch=False, duplicate=False,
        fast_calls=None, unresolved_layout=False):
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
        if fast_calls is not None:
            fast_calls.append(("full", image))
        active = image.name not in ("exam", "changed")
        chosen = next((c for c in cells if c["card_id"] == image.name), None)
        identity = {"card_id": "wrong" if mismatch else image.name, "upgrade": 1}
        return dict(active=active, layout_complete=active, hand_count=2, cards=cells,
                    selected=chosen["index"] if chosen else None, selected_card=identity,
                    detail=identity, agree=True, detail_lines=[{"text": "元気+7"}])

    fast = {}
    if fast_calls is not None:
        def layout(image):
            # Use the same synthetic facts without counting this as full OCR.
            result = read(image)
            fast_calls.pop()
            fast_calls.append(("layout", image))
            result["cards"] = [dict(c) for c in result["cards"]]
            if unresolved_layout:
                result["cards"][1]["card_id"] = None
            result["detail_lines"] = []
            return result

        def active(image):
            fast_calls.append(("active", image))
            return image.name not in ("exam", "changed")

        fast = dict(read_layout=layout, is_active=active)

    initial = current
    result = review_exam_hand_details(initial, hand, shoot=lambda: current, click=click,
        sleep=lambda _: None, same_state=lambda im: im.name == "exam",
        read_details=read, find_button=lambda _: (1, 1),
        close_buttons=lambda _: [] if missing_close else [(9, 9)], max_polls=2, **fast)
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
    assert taps == [(1, 1), (20, 20), (10, 10), (9, 9)]


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


def test_fast_paths_still_fully_read_each_selected_detail():
    calls = []
    result, _, _ = run(fast_calls=calls)
    assert result.restored and len(result.evidence) == 2
    assert [image.name for kind, image in calls if kind == "full"] == ["a", "b"]
    assert sum(kind == "layout" for kind, _ in calls) == 3
    assert [image.name for kind, image in calls if kind == "active"] == ["b", "exam"]


def test_unresolved_layout_recovers_using_full_reader_on_same_frame():
    calls = []
    result, _, _ = run(fast_calls=calls, unresolved_layout=True)
    assert result.restored and len(result.evidence) == 2
    for index, (kind, image) in enumerate(calls):
        if kind == "layout" and index > 0:
            assert calls[index + 1][0] == "full"
            assert calls[index + 1][1] is image


@pytest.mark.parametrize("restore", [True, False])
def test_unmatched_middle_upgrade_preserves_only_other_exact_evidence(restore):
    current, initial = Image("exam"), Image("exam")
    taps = []
    hand = [SimpleNamespace(slot=slot, card_id=key, upgrade=1)
            for slot, key in enumerate(("a", "b", "c"))]
    cells = [dict(index=slot, card_id=key, upgrade=0 if key == "b" else 1,
                  center=(slot + 10, 10)) for slot, key in enumerate(("c", "b", "a"))]

    def click(point):
        nonlocal current
        taps.append(point)
        if point == (1, 1):
            current = Image("modal")
        elif point == (9, 9):
            current = Image("exam" if restore else "changed")
        else:
            current = Image(next(c["card_id"] for c in cells if c["center"] == point))

    def read(image):
        cell = next((c for c in cells if c["card_id"] == image.name), None)
        identity = {"card_id": image.name, "upgrade": 0 if image.name == "b" else 1}
        return dict(active=image.name not in ("exam", "changed"), layout_complete=True,
                    hand_count=3, cards=cells, selected=cell["index"] if cell else None,
                    selected_card=identity, detail=identity, agree=True,
                    detail_lines=[{"text": "好印象+1"}])

    result = review_exam_hand_details(initial, hand, shoot=lambda: current, click=click,
        sleep=lambda _: None, same_state=lambda img: img.name == "exam",
        read_details=read, find_button=lambda _: (1, 1),
        close_buttons=lambda _: [(9, 9)], max_polls=2)
    assert taps == [(1, 1), (12, 10), (11, 10), (10, 10), (9, 9)]
    assert "selected_detail_identity_mismatch" in result.problems
    assert result.restored is restore
    if restore:
        assert [(e["slot"], e["card_id"], e["upgrade"]) for e in result.evidence] == [(0, "a", 1), (2, "c", 1)]
        assert all(e["snapshot_sha256"] == image_sha256(initial) for e in result.evidence)
    else:
        assert result.evidence == []


@pytest.mark.parametrize("title_grade,accepted", [(3, True), (1, False)])
def test_base_id_inspection_requires_exact_effective_title_grade(title_grade, accepted):
    current = Image("exam")
    initial = current
    taps = []
    hand = [SimpleNamespace(slot=2, card_id="card", upgrade=3)]
    cell = dict(index=0, card_id="card", upgrade=1, center=(10, 10))

    def click(point):
        nonlocal current
        taps.append(point)
        current = Image({(1,1): "modal", (10,10): "selected", (9,9): "exam"}[point])

    def read(image):
        return dict(active=image.name != "exam", layout_complete=True, hand_count=1,
                    cards=[cell], selected=0 if image.name == "selected" else None,
                    selected_card=None, detail={"card_id": "card", "upgrade": title_grade},
                    agree=False, detail_lines=[{"text": "actual effect"}])

    result = review_exam_hand_details(initial, hand, shoot=lambda: current, click=click,
        sleep=lambda _: None, same_state=lambda image: image.name == "exam",
        read_details=read, find_button=lambda _: (1,1), close_buttons=lambda _: [(9,9)], max_polls=2)
    assert result.restored
    assert taps == [(1,1), (10,10), (9,9)]
    assert bool(result.evidence) is accepted
    if accepted:
        assert result.evidence[0]["upgrade"] == 3
        assert result.evidence[0]["selected_card"] == {"slot": 2, "card_id": "card", "upgrade": 3}
        assert result.evidence[0]["observed_thumbnail_upgrade"] == 1


@pytest.mark.parametrize("duplicate_in", ["hand", "list"])
def test_base_id_fallback_forbidden_for_ambiguous_copies(duplicate_in):
    image = Image("exam")
    hand = [SimpleNamespace(slot=i, card_id="same" if duplicate_in == "hand" or i == 0 else "other",
                            upgrade=i+2) for i in range(2)]
    taps = []
    current = image
    cell = dict(index=0, card_id="same", upgrade=1, center=(10,10))
    def click(point):
        nonlocal current
        taps.append(point)
        current = Image("modal" if point == (1,1) else "exam")
    result = review_exam_hand_details(image, hand, shoot=lambda: current, click=click,
        sleep=lambda _: None, same_state=lambda img: img.name == "exam",
        read_details=lambda img: dict(active=img.name == "modal", layout_complete=True,
                                     hand_count=2, cards=[cell, dict(cell,index=1,
                                         card_id="other" if duplicate_in == "hand" else "same")]),
        find_button=lambda _: (1,1), close_buttons=lambda _: [(9,9)], max_polls=1)
    assert result.restored and not result.evidence
    assert taps == [(1,1), (9,9)]


@pytest.mark.parametrize("unknown_at", ["hand", "before_click", "after_click"])
def test_base_id_fallback_requires_all_known_base_ids(unknown_at):
    current = Image("exam")
    taps = []
    hand = [SimpleNamespace(slot=0, card_id="target", upgrade=3),
            SimpleNamespace(slot=1, card_id=None if unknown_at == "hand" else "other", upgrade=1)]
    def click(point):
        nonlocal current
        taps.append(point)
        current = Image({(1,1): "modal", (10,10): "selected", (9,9): "exam"}[point])
    def read(image):
        unknown = (unknown_at == "before_click" or
                   (unknown_at == "after_click" and image.name == "selected"))
        cells = [dict(index=0, card_id="target", upgrade=1, center=(10,10)),
                 dict(index=1, card_id=None if unknown else "unmatched", upgrade=0, center=(20,10))]
        return dict(active=image.name != "exam", layout_complete=True, hand_count=2,
                    cards=cells, selected=0 if image.name == "selected" else None,
                    selected_card=None, detail={"card_id":"target", "upgrade":3}, agree=False,
                    detail_lines=[{"text":"effect"}])
    result = review_exam_hand_details(current, hand, shoot=lambda: current, click=click,
        sleep=lambda _: None, same_state=lambda img: img.name == "exam", read_details=read,
        find_button=lambda _: (1,1), close_buttons=lambda _: [(9,9)], max_polls=1)
    assert result.restored and not result.evidence
    assert taps == ([(1,1), (10,10), (9,9)] if unknown_at == "after_click" else [(1,1), (9,9)])
