from types import SimpleNamespace
import threading

import numpy as np
import pytest

from hiro.platforms.windows import broker


def test_device_reconnect_keeps_server_alive_and_coordinates_logical(monkeypatch):
    calls = []

    class Client:
        size = (720, 1280)

        def capture(self):
            calls.append('capture')
            return np.zeros((1280, 720, 3), dtype=np.uint8)

        def input(self, op, **parameters):
            calls.append((op, parameters))

    monkeypatch.setattr(broker, 'BrokerClient', Client)
    first = broker.connect()
    assert first.screenshot().shape == (1280, 720, 3)
    first.click(360, 640)
    first.swipe(100, 400, 100, 200, .4)
    first.stop()
    second = broker.connect()
    second.click(500, 600)
    second.stop()
    assert ('click', {'x': 360, 'y': 640}) in calls
    assert ('swipe', {'x1':100, 'y1':400, 'x2':100, 'y2':200, 'duration':.4}) in calls
    assert ('click', {'x':500, 'y':600}) in calls
    assert all('shutdown' not in str(call) for call in calls)


def test_input_loss_is_not_retried(monkeypatch):
    calls = []

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args):
            calls.append(args)
            raise OSError('lost')

        def close(self):
            pass

    monkeypatch.setattr(broker.http.client, 'HTTPConnection', Connection)
    client = broker.BrokerClient.__new__(broker.BrokerClient)
    client._lock = threading.RLock()
    client.port, client._token, client.frame = 1234, 'secret', 'frame'
    with pytest.raises(RuntimeError, match='not retried'):
        client.input('click', x=1, y=2)
    assert len(calls) == 1


def test_capture_required_before_input():
    client = broker.BrokerClient.__new__(broker.BrokerClient)
    client._lock = threading.RLock()
    client.frame = None
    with pytest.raises(RuntimeError, match='Capture'):
        client.input('click', x=1, y=2)
