"""Opt-in elevated broker with a fixed, frame-checked native device interface."""
import argparse
import base64
from contextlib import contextmanager
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import stat
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
import uuid

MAX_BODY = 64 * 1024


class RequestError(ValueError):
    """A fixed validation diagnostic safe to return over RPC."""


def native_state(hwnd):
    import win32gui
    import win32process
    if not win32gui.IsWindow(hwnd):
        raise RequestError("Pinned game window no longer exists")
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return pid, tuple(win32gui.GetClientRect(hwnd))


class BrokerSession:
    def __init__(self, device, hwnd, game_pid, integrity, state_reader=native_state):
        self.device, self.hwnd, self.game_pid = device, hwnd, game_pid
        self.integrity, self.state_reader = integrity, state_reader
        self.frame = None
        self.geometry = None
        self.logical_size = None
        self.stopping = False

    def dispatch(self, request):
        if not isinstance(request, dict):
            raise RequestError("Request must be a JSON object")
        op = request.get("op")
        fields = {"status": set(), "capture": set(), "shutdown": set(),
                  "click": {"frame", "x", "y"},
                  "swipe": {"frame", "x1", "y1", "x2", "y2", "duration"}}
        if not isinstance(op, str) or op not in fields:
            raise RequestError("Unknown operation")
        if set(request) != fields[op] | {"op"}:
            raise RequestError("Invalid operation parameters")
        if op == "shutdown":
            self.stopping = True
            return {"shutdown": True}
        if op == "status":
            try:
                target_available = self.state_reader(self.hwnd)[0] == self.game_pid
            except Exception:
                target_available = False
            return dict(protocol=1, pid=os.getpid(), hwnd=self.hwnd, game_pid=self.game_pid,
                        integrity=self.integrity, logical_size=self.logical_size,
                        target_available=target_available)
        pid, geometry = self.state_reader(self.hwnd)
        if pid != self.game_pid:
            raise RequestError("Pinned game process changed")
        if op == "capture":
            import cv2
            image = self.device.screenshot()
            if image.ndim != 3 or image.shape[2] != 3:
                raise RequestError("Native screenshot must be normalized BGR")
            # A resize during capture cannot authorize a subsequent action.
            if self.state_reader(self.hwnd) != (pid, geometry):
                raise RequestError("Window changed during capture; capture again")
            ok, png = cv2.imencode(".png", image)
            if not ok:
                raise RequestError("PNG encoding failed")
            self.logical_size = [int(image.shape[1]), int(image.shape[0])]
            self.geometry, self.frame = geometry, uuid.uuid4().hex
            return dict(png=base64.b64encode(png).decode("ascii"), frame=self.frame,
                        shape=list(image.shape))
        if not self.frame or request["frame"] != self.frame:
            raise RequestError("Stale or missing frame; capture again")
        if geometry != self.geometry:
            self.frame = None
            raise RequestError("Window geometry changed; capture again")
        keys = ("x", "y") if op == "click" else ("x1", "y1", "x2", "y2")
        coords = [request[key] for key in keys]
        if any(type(value) is not int or not 0 <= value < self.logical_size[i % 2]
               for i, value in enumerate(coords)):
            raise RequestError("Coordinates outside logical image")
        if op == "swipe":
            duration = request["duration"]
            if (type(duration) not in (int, float) or not math.isfinite(duration)
                    or not 0.05 <= duration <= 3):
                raise RequestError("Swipe duration must be finite and between 0.05 and 3 seconds")
        # Consume authorization even when native input fails part-way through.
        self.frame = None
        if op == "click":
            self.device.click(*coords)
        else:
            self.device.swipe(*coords, duration=duration)
        self.frame = uuid.uuid4().hex
        return {"frame": self.frame}


class BrokerHTTPServer(HTTPServer):
    allow_reuse_address = False

    def __init__(self, session, token):
        self.session, self.token = session, token
        super().__init__(("127.0.0.1", 0), BrokerHandler)
        self.timeout = 0.5


class BrokerHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass  # Never log credentials or request contents.

    def send_error(self, code, message=None, explain=None):
        self.reply(code, {"ok": False, "error": "Invalid HTTP request"})

    def reply(self, status, body):
        data = json.dumps(body, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(data)

    def do_POST(self):
        if (self.path != "/rpc" or self.headers.get_all("Origin")
                or len(self.headers.get_all("Authorization", [])) != 1
                or not hmac.compare_digest(self.headers.get("Authorization", "").encode("utf-8"),
                                           ("Bearer " + self.server.token).encode("utf-8"))):
            return self.reply(403, {"ok": False, "error": "Unauthorized request"})
        try:
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
                raise RequestError("Content-Length required")
            length = int(lengths[0])
            if not 0 < length <= MAX_BODY:
                raise RequestError("Invalid payload size")
            data = self.rfile.read(length)
            if len(data) != length:
                raise RequestError("Incomplete payload")
            result = self.server.session.dispatch(json.loads(data))
        except RequestError as exc:
            return self.reply(400, {"ok": False, "error": str(exc)})
        except Exception:
            # Local stderr retains native diagnostics; HTTP never exposes them.
            traceback.print_exc()
            return self.reply(400, {"ok": False, "error": "Native operation failed; check broker stderr"})
        self.reply(200, {"ok": True, "result": result})


def secure_directory(path):
    """Protect the parent before any credential bytes are written."""
    import win32api
    import win32con
    import win32security
    import ntsecuritycon
    for parent in (path, *path.parents):
        if parent.exists() and parent.stat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise RequestError("Credential directory must not traverse a reparse point")
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RequestError("Credential directory must not be a symlink")
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()
    acl = win32security.ACL()
    for principal in (sid, win32security.CreateWellKnownSid(win32security.WinLocalSystemSid),
                      win32security.CreateWellKnownSid(win32security.WinBuiltinAdministratorsSid)):
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION,
                                 win32con.OBJECT_INHERIT_ACE | win32con.CONTAINER_INHERIT_ACE,
                                 ntsecuritycon.FILE_ALL_ACCESS, principal)
    win32security.SetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
                                      win32security.DACL_SECURITY_INFORMATION |
                                      win32security.PROTECTED_DACL_SECURITY_INFORMATION,
                                      None, None, acl, None)


@contextmanager
def keep_awake():
    """Hold this broker thread's display/system wake request, then restore it."""
    import ctypes
    api = ctypes.WinDLL("kernel32", use_last_error=True).SetThreadExecutionState
    api.argtypes = [ctypes.c_uint32]
    api.restype = ctypes.c_uint32
    previous = api(0x80000000 | 0x00000001 | 0x00000002)
    if not previous:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        api(previous)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path("reports/windows-broker/session.json"))
    args = parser.parse_args(argv)
    from .target import resolve, ensure_input_access, integrity_level
    from .device import connect
    window, _ = resolve()
    hwnd, game_pid = int(window.info.id), int(window.info.process_id)
    os.environ["HIRO_WINDOW_HWND"] = str(hwnd)
    ensure_input_access(window)
    device = connect("windows_sendinput")
    secret = secrets.token_urlsafe(32)
    state = args.state.absolute()
    server = None
    wrote_state = False
    try:
        session = BrokerSession(device, hwnd, game_pid, integrity_level(os.getpid()))
        server = BrokerHTTPServer(session, secret)
        secure_directory(state.parent)
        # Exclusive creation never follows or overwrites another session's file.
        with state.open("x", encoding="utf-8") as stream:
            wrote_state = True
            json.dump(dict(protocol=1, pid=os.getpid(), port=server.server_port,
                           token=secret, hwnd=hwnd, game_pid=game_pid), stream)
        with keep_awake():
            while not session.stopping:
                server.handle_request()
    finally:
        if server:
            server.server_close()
        try:
            device.stop()
        finally:
            if wrote_state:
                try:
                    saved = json.loads(state.read_text(encoding="utf-8"))
                    if saved.get("token") == secret and saved.get("pid") == os.getpid():
                        state.unlink()
                except (OSError, ValueError):
                    pass


if __name__ == "__main__":
    main()
