"""The fixes behind the Hermes compression stall, tested without a GPU.

A fake llama-server stands in for the real one: it streams slowly or sits on
a request, and records the moment the router hangs up on it. That moment is
the whole point — on 2026-10-07 the real server kept generating for 5 more
minutes after the agent had given up, with the router's lock held.
"""
import http.client
import json
import pathlib
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import router  # noqa: E402


class FakeLlama:
    """Upstream stub. mode: 'json' answers at once, 'sse' streams a token per
    0.2 s for 60 s, 'hang' never answers. `closed_at` is when the router's
    connection to it went away."""

    def __init__(self, mode):
        self.mode = mode
        self.closed_at = None
        self.first_chunk_sent_at = None
        owner = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if owner.mode == "json":
                    data = json.dumps({"ok": True}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if owner.mode == "sse":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    try:
                        for i in range(300):
                            self.wfile.write(f"data: {{\"tok\": {i}}}\n\n".encode())
                            self.wfile.flush()
                            if owner.first_chunk_sent_at is None:
                                owner.first_chunk_sent_at = time.monotonic()
                            time.sleep(0.2)
                    except OSError:
                        owner.closed_at = time.monotonic()
                    return
                # hang: like a long non-streamed generation. Detect the close.
                while True:
                    try:
                        if self.connection.recv(1, socket.MSG_PEEK) == b"":
                            owner.closed_at = time.monotonic()
                            return
                    except OSError:
                        owner.closed_at = time.monotonic()
                        return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.addr = self.server.server_address
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()


class Front(BaseHTTPRequestHandler):
    """Minimal router front: just the forwarding call under test."""
    protocol_version = "HTTP/1.1"
    result = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        Front.result.append(router.forward_live(self, self.path, body, dict(self.headers),
                                                poll=0.1))


@pytest.fixture
def stack(monkeypatch):
    made = []

    def make(mode):
        up = FakeLlama(mode)
        monkeypatch.setattr(router, "UPSTREAM_ADDR", up.addr)
        front = ThreadingHTTPServer(("127.0.0.1", 0), Front)
        threading.Thread(target=front.serve_forever, daemon=True).start()
        Front.result = []
        made.extend([up, front])
        return up, front.server_address

    yield make
    for s in made:
        (s.stop if isinstance(s, FakeLlama) else s.shutdown)()


def raw_post(addr):
    sock = socket.create_connection(addr)
    body = b'{"model":"x"}'
    sock.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nHost: t\r\n"
                 b"Content-Type: application/json\r\n"
                 + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    return sock


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_plain_response_is_forwarded(stack):
    _, addr = stack("json")
    conn = http.client.HTTPConnection(*addr, timeout=10)
    conn.request("POST", "/v1/chat/completions", b"{}", {"Content-Type": "application/json"})
    resp = conn.getresponse()
    assert resp.status == 200
    assert json.load(resp) == {"ok": True}


def test_sse_reaches_the_client_before_generation_ends(stack):
    # The old forward() buffered the whole stream: the first byte arrived with
    # the last one, so the agent saw "no progress" for the entire generation.
    up, addr = stack("sse")
    sock = raw_post(addr)
    sock.settimeout(5)
    got = b""
    while b"data:" not in got:
        got += sock.recv(4096)
    assert up.closed_at is None, "upstream must still be generating"
    sock.close()


def test_hangup_during_sse_cancels_upstream(stack):
    up, addr = stack("sse")
    sock = raw_post(addr)
    assert wait_for(lambda: up.first_chunk_sent_at is not None)
    hung_up = time.monotonic()
    sock.close()
    assert wait_for(lambda: up.closed_at is not None), "upstream kept streaming to nobody"
    assert up.closed_at - hung_up < 3
    assert wait_for(lambda: Front.result == ["cancelled"])


def test_hangup_during_plain_request_cancels_upstream(stack):
    # Hermes' summary call is not streamed: the router sits in getresponse()
    # and only the socket watcher can notice the client is gone.
    up, addr = stack("hang")
    sock = raw_post(addr)
    time.sleep(0.5)
    hung_up = time.monotonic()
    sock.close()
    assert wait_for(lambda: up.closed_at is not None), "upstream kept the slot busy"
    assert up.closed_at - hung_up < 3
    assert wait_for(lambda: Front.result == ["cancelled"])


def test_client_gone_ignores_pipelined_data():
    a, b = socket.socketpair()
    try:
        assert not router.client_gone(a)
        b.sendall(b"GET / HTTP/1.1\r\n")
        assert not router.client_gone(a), "pending data is not a hang-up"
        b.close()
        a.recv(64)
        assert router.client_gone(a)
    finally:
        a.close()


def test_cap_adds_a_ceiling_only_when_missing(monkeypatch):
    monkeypatch.setattr(router, "DEFAULT_MAX_TOKENS", 4096)
    p = {"model": "m", "messages": []}
    assert router.cap_max_tokens(p) is True
    assert p["max_tokens"] == 4096
    for key in ("max_tokens", "max_completion_tokens", "n_predict"):
        explicit = {"model": "m", key: 50000}
        assert router.cap_max_tokens(explicit) is False
        assert explicit[key] == 50000, "an explicit client value always wins"


def test_default_cap_leaves_room_for_a_hermes_summary(monkeypatch):
    # Hermes sends its compression summary uncapped on purpose and discards it
    # on finish_reason=length. A 4096 cap cut ornith off mid-reasoning (15K
    # chars of thinking, no summary). Hermes asks for up to 10K summary tokens.
    import importlib
    monkeypatch.delenv("IA_DEFAULT_MAX_TOKENS", raising=False)
    fresh = importlib.reload(router)
    assert fresh.DEFAULT_MAX_TOKENS >= 16384


def test_cap_can_be_disabled_and_skips_bad_bodies(monkeypatch):
    monkeypatch.setattr(router, "DEFAULT_MAX_TOKENS", 0)
    p = {"model": "m"}
    assert router.cap_max_tokens(p) is False and "max_tokens" not in p
    monkeypatch.setattr(router, "DEFAULT_MAX_TOKENS", 4096)
    assert router.cap_max_tokens({}) is False  # unparsable body → forward as-is


def test_every_model_runs_with_a_single_slot():
    # With 4 slots the 64K KV cells are shared, and a side request evicted the
    # agent's 55K-token conversation ("failed to find 55298 available cells").
    for model in router.MODELS:
        flags = router.server_flags(model).split()
        assert "--parallel" in flags, model
        assert flags[flags.index("--parallel") + 1] == "1", model
