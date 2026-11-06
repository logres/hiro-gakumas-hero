import http.client
import json
import io
import errno
import socket
import threading
from email.message import Message

import numpy as np
import pytest

from hiro.platforms.windows.broker_server import BrokerHandler, BrokerHTTPServer, BrokerSession, MAX_BODY, keep_awake


class Device:
    def __init__(self):
        self.inputs = []

    def screenshot(self):
        return np.zeros((1280, 720, 3), dtype=np.uint8)

    def click(self, *args):
        self.inputs.append(args)

    def swipe(self, *args, **kwargs):
        self.inputs.append((args, kwargs))


@pytest.fixture
def session():
    state = [45, (0, 0, 450, 800)]
    result = BrokerSession(Device(), 123, 45, 12288, lambda hwnd: tuple(state))
    result.test_state = state
    return result


def capture(session):
    return session.dispatch({"op": "capture"})["frame"]


def test_capture_normalized_png_and_status(session):
    result = session.dispatch({"op": "capture"})
    assert result["shape"] == [1280, 720, 3]
    assert result["png"].startswith("iVBOR")
    assert session.dispatch({"op": "status"})["logical_size"] == [720, 1280]
    assert capture(session) != result["frame"]


@pytest.mark.parametrize("x,y", [(-1, 0), (720, 0), (0, 1280), (True, 1), (1.2, 0)])
def test_bounds_never_input(session, x, y):
    with pytest.raises(ValueError):
        session.dispatch(dict(op="click", frame=capture(session), x=x, y=y))
    assert session.device.inputs == []


def test_frame_rotation_and_stale_rejection(session):
    frame = capture(session)
    result = session.dispatch(dict(op="click", frame=frame, x=719, y=1279))
    assert result["frame"] != frame
    with pytest.raises(ValueError):
        session.dispatch(dict(op="click", frame=frame, x=0, y=0))
    assert session.device.inputs == [(719, 1279)]


def test_geometry_and_identity_fail_closed(session):
    frame = capture(session)
    session.test_state[1] = (0, 0, 451, 800)
    with pytest.raises(ValueError):
        session.dispatch(dict(op="click", frame=frame, x=0, y=0))
    session.test_state[0] = 46
    with pytest.raises(ValueError):
        session.dispatch({"op": "capture"})
    assert session.dispatch({"op": "status"})["target_available"] is False
    assert not session.stopping
    assert session.device.inputs == []


def test_target_gone_status_and_shutdown_still_work(session):
    def gone(hwnd):
        raise RuntimeError("Target disappeared")
    session.state_reader = gone
    status = session.dispatch({"op": "status"})
    assert status["target_available"] is False
    assert status["game_pid"] == 45
    assert status["integrity"] == 12288
    assert session.dispatch({"op": "shutdown"}) == {"shutdown": True}
    assert session.stopping
    assert session.device.inputs == []


def test_keep_awake_restores_on_error(monkeypatch):
    import ctypes
    from types import SimpleNamespace
    calls = []
    def execution_state(flags):
        calls.append(flags)
        return 0x80000000
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: SimpleNamespace(
        SetThreadExecutionState=execution_state), raising=False)
    with pytest.raises(RuntimeError):
        with keep_awake():
            raise RuntimeError("stop")
    assert calls == [0x80000003, 0x80000000]


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), 0, 3.1, True, "1"])
def test_swipe_duration_rejected(session, duration):
    with pytest.raises(ValueError):
        session.dispatch(dict(op="swipe", frame=capture(session), x1=0, y1=0,
                              x2=719, y2=1279, duration=duration))
    assert session.device.inputs == []


def test_swipe_and_unknown_operations(session):
    frame = capture(session)
    session.dispatch(dict(op="swipe", frame=frame, x1=0, y1=1, x2=2, y2=3, duration=.05))
    assert session.device.inputs == [((0, 1, 2, 3), {"duration": .05})]
    for request in ({"op": "exec"}, {"op": "status", "path": "foo"}, []):
        with pytest.raises(ValueError):
            session.dispatch(request)


@pytest.mark.parametrize("headers,body,expected", [
    ({}, '{"op":"capture"}', 403),
    ({"Authorization": "Bearer wrong"}, '{"op":"capture"}', 403),
    ({"Authorization": "Bearer secret", "Origin": "null"}, '{"op":"capture"}', 403),
    ({"Authorization": "Bearer secret"}, '{"op":"exec"}', 400),
    ({"Authorization": "Bearer secret"}, 'x' * (MAX_BODY + 1), 400),
    ({"Authorization": "Bearer secret"}, '{"op":"status"}', 200),
])
def test_local_http_auth_and_transport(session, headers, body, expected):
    with BrokerHTTPServer(session, "secret") as server:
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        connection = None
        try:
            try:
                connection = socket.create_connection(("127.0.0.1", server.server_port), timeout=3)
            except PermissionError:
                pytest.skip("App sandbox blocks loopback connections")
            try:
                payload = body.encode("utf-8")
                request_headers = {"Host": "127.0.0.1", "Content-Length": str(len(payload)), **headers}
                request = "POST /rpc HTTP/1.1\r\n" + "".join(
                    f"{name}: {value}\r\n" for name, value in request_headers.items())
                # Send headers and body together: http.client.request otherwise
                # races an early rejection against its separate body write.
                connection.sendall(request.encode("ascii") + b"\r\n" + payload)
                response = http.client.HTTPResponse(connection)
                response.begin()
                assert response.status == expected
                assert response.getheader("Connection") == "close"
                assert json.loads(response.read())["ok"] == (expected == 200)
            except OSError as exc:
                # Early auth/size rejection deliberately leaves the body unread.
                # Windows may reset TCP before that rejection response arrives;
                # direct-handler tests below verify both rejection paths without
                # reading the body or dispatching. Other resets still fail.
                oversized = expected == 400 and len(body.encode()) > MAX_BODY
                unauthorized = expected == 403 and (
                    headers.get("Authorization") != "Bearer secret" or "Origin" in headers)
                reset = getattr(exc, "winerror", None) in (10053, 10054) or exc.errno == errno.ECONNRESET
                if not ((oversized or unauthorized) and reset):
                    raise
        finally:
            if connection:
                connection.close()
            thread.join(5)
        assert not thread.is_alive()
    assert session.device.inputs == []


@pytest.mark.parametrize("authorization,origin,op,status", [
    (None, None, "capture", 403), ("Bearer wrong", None, "capture", 403),
    ("Bearer secret", "null", "capture", 403),
    ("Bearer secret", None, "exec", 400), ("Bearer secret", None, "status", 200),
])
def test_handler_without_network(session, authorization, origin, op, status):
    from types import SimpleNamespace
    handler = object.__new__(BrokerHandler)
    handler.path = "/rpc"
    handler.headers = Message()
    body = json.dumps({"op": op}).encode()
    handler.headers["Content-Length"] = str(len(body))
    if authorization:
        handler.headers["Authorization"] = authorization
    if origin:
        handler.headers["Origin"] = origin
    handler.rfile = io.BytesIO(body)
    handler.server = SimpleNamespace(session=session, token="secret")
    replies = []
    handler.reply = lambda *args: replies.append(args)
    handler.do_POST()
    assert replies[0][0] == status
    assert session.device.inputs == []


def test_oversized_handler_rejects_before_read_or_dispatch(session):
    from types import SimpleNamespace
    handler = object.__new__(BrokerHandler)
    handler.path = "/rpc"
    handler.headers = Message()
    handler.headers["Authorization"] = "Bearer secret"
    handler.headers["Content-Length"] = str(MAX_BODY + 1)

    def unexpected(*args):
        pytest.fail("Oversized request must not read its body or dispatch an operation")

    handler.rfile = SimpleNamespace(read=unexpected)
    handler.server = SimpleNamespace(session=SimpleNamespace(dispatch=unexpected), token="secret")
    replies = []
    handler.reply = lambda *args: replies.append(args)
    handler.do_POST()
    assert replies == [(400, {"ok": False, "error": "Invalid payload size"})]
    assert session.device.inputs == []


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"},
    {"Authorization": "Bearer secret", "Origin": "null"}])
def test_unauthorized_handler_rejects_before_read_or_dispatch(headers):
    from types import SimpleNamespace
    handler = object.__new__(BrokerHandler)
    handler.path = "/rpc"
    handler.headers = Message()
    handler.headers["Content-Length"] = "16"
    for name, value in headers.items():
        handler.headers[name] = value

    def unexpected(*args):
        pytest.fail("Unauthorized request must not read its body or dispatch an operation")

    handler.rfile = SimpleNamespace(read=unexpected)
    handler.server = SimpleNamespace(session=SimpleNamespace(dispatch=unexpected), token="secret")
    replies = []
    handler.reply = lambda *args: replies.append(args)
    handler.do_POST()
    assert replies == [(403, {"ok": False, "error": "Unauthorized request"})]
