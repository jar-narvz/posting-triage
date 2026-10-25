"""FilteringProxy: every connection is checked, allowed ones are relayed, blocked ones never
reach the server. Local servers stand in for websites; the injected check allows only the
`allowed` server's port, the way public_destination allows only public addresses."""

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from posting_triage.proxy import FilteringProxy, public_destination
from posting_triage.urlguard import BlockedURL


class Site:
    """A local web server that records each request's path and headers."""

    def __init__(self, body):
        self.requests = []
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                site.requests.append((self.path, dict(self.headers)))
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def sites():
    allowed, blocked = Site(b"public page"), Site(b"SECRET")
    yield allowed, blocked
    allowed.close()
    blocked.close()


@pytest.fixture
def proxy(sites):
    allowed, _ = sites

    def check(host, port):
        if port != allowed.port:
            raise BlockedURL("not public")
        return ["127.0.0.1"]

    with FilteringProxy(check, timeout=5) as p:
        yield p


def send(proxy, data):
    """Send raw bytes to the proxy and read until it closes the connection."""
    port = int(proxy.url.rsplit(":", 1)[1])
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(data)
        chunks = []
        while chunk := s.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks)


def get(port, path="/job"):
    return (f"GET http://127.0.0.1:{port}{path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            "Proxy-Connection: keep-alive\r\n\r\n").encode()


def test_an_allowed_http_request_is_forwarded_as_one_request(proxy, sites):
    allowed, _ = sites
    response = send(proxy, get(allowed.port))
    assert response.startswith(b"HTTP/1.0 200") and response.endswith(b"public page")
    path, headers = allowed.requests[0]
    assert path == "/job"  # origin-form, not the full URL
    assert headers["Connection"] == "close"
    assert "Proxy-Connection" not in headers


def test_a_blocked_http_request_never_reaches_the_server(proxy, sites):
    _, blocked = sites
    assert send(proxy, get(blocked.port)).startswith(b"HTTP/1.1 403")
    assert blocked.requests == []
    assert proxy.blocked == [("127.0.0.1", blocked.port, "not public")]


def test_a_second_request_on_the_same_connection_is_not_relayed(proxy, sites):
    # The keep-alive trap: an allowed request, then one to a blocked host on the same socket.
    allowed, blocked = sites
    response = send(proxy, get(allowed.port) + get(blocked.port))
    assert b"SECRET" not in response
    assert len(allowed.requests) == 1
    assert blocked.requests == []


def test_an_allowed_connect_tunnels_bytes_both_ways(proxy, sites):
    allowed, _ = sites
    port = int(proxy.url.rsplit(":", 1)[1])
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(f"CONNECT 127.0.0.1:{allowed.port} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        assert s.recv(65536) == b"HTTP/1.1 200 Connection Established\r\n\r\n"
        s.sendall(b"GET /through-the-tunnel HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        response = b""
        while chunk := s.recv(65536):
            response += chunk
    assert response.endswith(b"public page")
    assert allowed.requests[0][0] == "/through-the-tunnel"


def test_a_blocked_connect_is_refused(proxy, sites):
    _, blocked = sites
    response = send(proxy, f"CONNECT 127.0.0.1:{blocked.port} HTTP/1.1\r\n\r\n".encode())
    assert response.startswith(b"HTTP/1.1 403")
    assert blocked.requests == []


@pytest.mark.parametrize("request_bytes, status", [
    (b"POST http://127.0.0.1:1/ HTTP/1.1\r\n\r\n", b"405"),
    (b"CONNECT nonsense HTTP/1.1\r\n\r\n", b"400"),
    (b"GET https://127.0.0.1/ HTTP/1.1\r\n\r\n", b"400"),  # https must come as CONNECT
    (b"garbage\r\n\r\n", b"400"),
])
def test_malformed_or_unsupported_requests_are_refused(proxy, request_bytes, status):
    assert send(proxy, request_bytes).startswith(b"HTTP/1.1 " + status)


def test_an_unreachable_allowed_server_is_a_502(sites):
    allowed, _ = sites
    allowed.close()  # the check passes, but nothing is listening any more
    with FilteringProxy(lambda host, port: ["127.0.0.1"], timeout=5) as p:
        assert send(p, get(allowed.port)).startswith(b"HTTP/1.1 502")


@pytest.mark.parametrize("host, port", [("127.0.0.1", 443), ("localhost", 80), ("example.com", 8080)])
def test_the_default_check_refuses_loopback_and_other_ports(host, port):
    with pytest.raises(BlockedURL):
        public_destination(host, port)
