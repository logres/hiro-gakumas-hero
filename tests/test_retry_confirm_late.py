# 来源：digital-hiro tests/test_retry_confirm_late.py（c3fc27f）
"""第二十局 04:06：点「再挑戦」后确认框 6 秒后才弹，旧逻辑窗口过了就当成已再挑戦，没点「決定」。"""

from types import SimpleNamespace as NS

import hiro.produce.hif as hif
from hiro.produce.hif import HiroHifStrategy


def b(text, y):
    return NS(text=text, rect=NS(center=NS(x=500, y=y)))


DIALOG = [b("再挑戦確認", 420), b("再挑戦チケットを消費して、試験に再挑戦しますか？", 650), b("本日あと1回無料", 940),
          b("✕キャンセル", 1160), b("決定", 1160)]  # fmt: skip


def test_late_confirm_dialog_is_pressed(monkeypatch, tmp_path):
    clock = {"t": 0.0}
    calls = {"n": 0}
    clicks = []

    def ocr_():
        calls["n"] += 1
        if clicks and len(clicks) >= 2:
            return [b("試験開始", 300)]  # 确认关闭后进入考试准备页
        return DIALOG if clock["t"] >= 8.0 else [b("敗退", 300)]  # 8 秒后才弹

    monkeypatch.setattr(hif, "ocr", NS(ocr=ocr_))
    monkeypatch.setattr(hif, "device", NS(click=lambda r: clicks.append(r), screenshot=lambda: None))
    monkeypatch.setattr(hif, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    monkeypatch.setattr(hif.time, "monotonic", lambda: clock["t"])
    st = HiroHifStrategy.__new__(HiroHifStrategy)
    st._retries_so_far = lambda label: 0
    st.s = NS(note=lambda *a: None, trace=NS(dir=tmp_path / "run"))
    kind = st._click_retry("r2", b("再挑戦", 1160), [b("再挑戦", 1160), b("本日あと1回無料", 940)])
    assert kind == "free"
    assert len(clicks) == 2 and clicks[1].center.y == 1160  # 第 2 下点的是确认框「決定」
