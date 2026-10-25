"""Decision 9 for the browser: a local forward proxy that Chromium is forced through.

Checking only the starting URL isn't enough: a page can redirect, embed an iframe, or run
a script that reaches 169.254.170.2, and Playwright's request hook never sees redirects.
A proxy sees every connection the browser makes, so it checks each one the same way
urlguard checks the starting URL, and connects to the exact address it checked (a second
DNS lookup could answer differently).

HTTPS arrives as CONNECT host:443: the proxy checks the host, then relays encrypted bytes
both ways without reading them. Plain HTTP arrives as one request with a full URL: the
proxy checks it, forwards that one request with Connection: close, then hangs up, so a
reused connection can't carry a second, unchecked request to another host.
"""

import select
import socket
import threading
from socketserver import StreamRequestHandler, ThreadingTCPServer
from urllib.parse import urlsplit

from posting_triage.urlguard import PORTS, BlockedURL, public_host

MAX_HEADER_LINES = 100
DROPPED_HEADERS = ("proxy-connection", "proxy-authorization", "connection", "keep-alive")


def public_destination(host, port):
    """The default check: ports 80 and 443 only, and every address public."""
    if port not in PORTS:
        raise BlockedURL("only ports 80 and 443 are allowed")
    return public_host(host, port)


class FilteringProxy:
    """A proxy on 127.0.0.1 for one browser. `check(host, port)` returns the addresses to
    connect to or raises BlockedURL; it's swappable so tests can allow a local server.

        with FilteringProxy() as proxy:
            chromium.launch(proxy={"server": proxy.url})
    """

    def __init__(self, check=public_destination, timeout=30):
        self.check, self.timeout = check, timeout
        self.blocked = []  # (host, port, reason) for every refused connection

    def __enter__(self):
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.proxy = self
        # A short poll interval so shutdown() returns at once instead of after up to 0.5 s.
        threading.Thread(target=self._server.serve_forever, args=(0.05,), daemon=True).start()
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()

    def open(self, host, port):
        """A socket to `host`, connected to an address `check` approved."""
        addresses = self.check(host, port)
        error = OSError(f"no address for {host}")
        for address in addresses:
            try:
                return socket.create_connection((address, port), timeout=self.timeout)
            except OSError as e:
                error = e
        raise error


class _Server(ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class _Handler(StreamRequestHandler):
    rbufsize = 0  # unbuffered: after CONNECT, no client bytes may sit in a read buffer

    def handle(self):
        proxy = self.server.proxy
        self.connection.settimeout(proxy.timeout)
        try:
            request_line = self.rfile.readline(65537).decode("latin-1").split()
            headers = self.read_headers()
        except (OSError, UnicodeDecodeError):
            return
        if len(request_line) != 3 or headers is None:
            return self.reply(400)
        method, target, _ = request_line
        if method == "CONNECT":
            self.tunnel(proxy, target)
        elif method in ("GET", "HEAD"):
            self.forward(proxy, method, target, headers)
        else:
            self.reply(405)  # page loads only need GET and HEAD over plain HTTP

    def read_headers(self):
        headers = []
        for _ in range(MAX_HEADER_LINES):
            line = self.rfile.readline(65537).decode("latin-1")
            if line in ("\r\n", "\n", ""):
                return headers
            headers.append(line.rstrip("\r\n"))
        return None

    def tunnel(self, proxy, target):
        host, _, port = target.rpartition(":")
        host = host.strip("[]")
        if not host or not port.isdigit():
            return self.reply(400)
        upstream = self.connect(proxy, host, int(port))
        if upstream is None:
            return
        with upstream:
            self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            relay(self.connection, upstream, proxy.timeout)

    def forward(self, proxy, method, target, headers):
        parts = urlsplit(target)
        if parts.scheme != "http" or not parts.hostname:
            return self.reply(400)
        try:
            port = parts.port or 80
        except ValueError:
            return self.reply(400)
        upstream = self.connect(proxy, parts.hostname, port)
        if upstream is None:
            return
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        kept = [h for h in headers if h.split(":", 1)[0].strip().lower() not in DROPPED_HEADERS]
        request = "\r\n".join([f"{method} {path} HTTP/1.1", *kept, "Connection: close", "", ""])
        with upstream:
            upstream.sendall(request.encode("latin-1"))
            relay(self.connection, upstream, proxy.timeout)
        # Returning closes the client connection: one request per connection.

    def connect(self, proxy, host, port):
        """The upstream socket, or None after replying 403 (blocked) or 502 (unreachable)."""
        try:
            return proxy.open(host, port)
        except BlockedURL as e:
            proxy.blocked.append((host, port, str(e)))
            self.reply(403)
        except OSError:
            self.reply(502)
        return None

    def reply(self, status):
        reasons = {400: "Bad Request", 403: "Forbidden", 405: "Method Not Allowed", 502: "Bad Gateway"}
        self.wfile.write(f"HTTP/1.1 {status} {reasons[status]}\r\nConnection: close\r\n"
                         "Content-Length: 0\r\n\r\n".encode())


def relay(a, b, idle_timeout):
    """Copy bytes both ways until either side closes or nothing moves for `idle_timeout`."""
    sockets = [a, b]
    while True:
        readable, _, _ = select.select(sockets, [], [], idle_timeout)
        if not readable:
            return
        for s in readable:
            try:
                data = s.recv(65536)
            except OSError:
                return
            if not data:
                return
            (b if s is a else a).sendall(data)
