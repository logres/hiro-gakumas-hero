"""Unprivileged kotonebot provider for the persistent Windows input broker.

Disconnecting this provider never shuts down the elevated process. No request
is retried: a lost response to input has an unknown outcome, not a safe retry.
"""
import base64
import http.client
import json
import os
import threading
from pathlib import Path


class BrokerClient:
    def __init__(self, state_path=None):
        path = Path(state_path or os.environ.get('HIRO_WINDOWS_BROKER_STATE',
                                                'reports/windows-broker/session.json'))
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise RuntimeError('Windows broker unavailable; start scripts/start-windows-broker.ps1 first') from exc
        if (state.get('protocol') != 1 or type(state.get('port')) is not int
                or not 1 <= state['port'] <= 65535 or not isinstance(state.get('token'), str)
                or len(state['token']) < 32):
            raise RuntimeError('Invalid Windows broker session metadata')
        self.port = state['port']
        self._lock = threading.RLock()
        self._token = state['token']
        self.frame = None
        self.size = (720, 1280)
        self.status = self.call('status')
        if self.status.get('protocol') != 1 or self.status.get('pid') != state.get('pid'):
            raise RuntimeError('Windows broker identity changed; reconnect explicitly')

    def call(self, op, **parameters):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        try:
            connection.request('POST', '/rpc', json.dumps({'op': op, **parameters}),
                               {'Authorization': 'Bearer ' + self._token,
                                'Content-Type': 'application/json'})
            response = connection.getresponse()
            raw = response.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise RuntimeError('Broker response exceeds image limit')
            data = json.loads(raw)
            if response.status != 200 or not data.get('ok'):
                raise RuntimeError('Windows broker: ' + str(data.get('error', 'request rejected')))
            return data['result']
        except (OSError, http.client.HTTPException) as exc:
            raise RuntimeError('Broker connection lost; operation outcome unknown, not retried') from exc
        finally:
            connection.close()

    def capture(self):
        with self._lock:
            return self._capture()

    def _capture(self):
        import cv2
        import numpy as np
        result = self.call('capture')
        frame = cv2.imdecode(np.frombuffer(base64.b64decode(result['png'], validate=True),
                                          dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None or list(frame.shape) != result['shape']:
            raise RuntimeError('Invalid broker screenshot')
        self.frame = result['frame']
        self.size = (frame.shape[1], frame.shape[0])
        return frame

    def input(self, op, **parameters):
        with self._lock:
            if self.frame is None:
                raise RuntimeError('Capture before input')
            result = self.call(op, frame=self.frame, **parameters)
            self.frame = result['frame']


def connect(backend='auto'):
    if backend not in ('auto', 'windows_broker'):
        raise ValueError('Broker provider supports auto or windows_broker only')
    from kotonebot.client.device import WindowsDevice
    from kotonebot.client.scaler import ProportionalScaler
    from kotonebot.primitives.geometry import Size

    client = BrokerClient()

    class LogicalScaler(ProportionalScaler):
        # Server already normalized the frame and owns physical conversion.
        def transform_screenshot(self, image):
            self.physical_resolution = Size(image.shape[1], image.shape[0])
            return image

        def logic_to_physical(self, value):
            return value

        def physical_to_logic(self, value):
            return value

    class Remote:
        @property
        def screen_size(self):
            return client.size

        def detect_orientation(self):
            return 'landscape' if client.size[0] > client.size[1] else 'portrait'

        def screenshot(self):
            return client.capture()

        def click(self, x, y):
            client.input('click', x=int(x), y=int(y))

        def swipe(self, x1, y1, x2, y2, duration=None):
            client.input('swipe', x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
                         duration=.3 if duration is None else duration)

    scaler = LogicalScaler()
    scaler.logic_resolution = Size(720, 1280)
    scaler.physical_resolution = Size(720, 1280)
    driver = Remote()
    device = WindowsDevice()
    device.setup(screenshot=driver, touch=driver, scaler=scaler)
    device.start()
    try:
        device.screenshot()
    except BaseException:
        device.stop()
        raise
    return device


def real_click(lx, ly):
    device = connect()
    try:
        device.click(lx, ly)
    finally:
        device.stop()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Inspect or explicitly stop the Windows broker')
    parser.add_argument('operation', choices=['status', 'shutdown'], default='status', nargs='?')
    args = parser.parse_args()
    print(json.dumps(BrokerClient().call(args.operation)))
