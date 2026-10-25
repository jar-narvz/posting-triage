"""Decision 9: the API fetches only public http(s) URLs, never localhost, private ranges,
or link-local addresses such as the cloud metadata address 169.254.169.254.

The check resolves the hostname and tests every address it returns: names like
"localtest.me" or "2130706433" look harmless as text but reach 127.0.0.1.
The browser's traffic all goes through proxy.py, which runs the same address check on
every connection, so a redirect or a subresource can't reach what the starting URL couldn't.
"""

import ipaddress
import re
import socket
from urllib.parse import urlsplit

SCHEMES = ("http", "https")
PORTS = (80, 443)
NAT64 = ipaddress.ip_network("64:ff9b::/96")  # IPv6 wrapper around an IPv4 address
# Browsers read a host whose last label is a number ("0177.0.0.1", "0x7f.1") as an IPv4
# address, sometimes in octal or hex; the system resolver may read it differently.
NUMERIC_LABEL = re.compile(r"(0x[0-9a-f]*|[0-9]+)", re.IGNORECASE)


class BlockedURL(ValueError):
    """A URL the API won't fetch. The message says why, for the 400 response."""


def public_url(url, resolve=socket.getaddrinfo):
    """Return `url` if it's safe to fetch, else raise BlockedURL.
    `resolve` is swappable so tests never touch DNS."""
    parts = urlsplit(url)
    if parts.scheme.lower() not in SCHEMES:
        raise BlockedURL("only http and https URLs are allowed")
    if "@" in parts.netloc:
        raise BlockedURL("URLs with a username or password are not allowed")
    if not parts.hostname:
        raise BlockedURL("the URL has no hostname")
    try:
        port = parts.port
    except ValueError:
        raise BlockedURL("the URL's port is not a number from 0 to 65535") from None
    if port is not None and port not in PORTS:
        raise BlockedURL("only ports 80 and 443 are allowed")
    public_host(parts.hostname, port or 443, resolve)
    return url


def public_host(host, port, resolve=socket.getaddrinfo):
    """The addresses `host` resolves to, sorted; raise BlockedURL unless every one is public.
    A caller that connects should use these addresses, not resolve the name again: a second
    lookup could answer differently (DNS rebinding)."""
    last_label = host.rstrip(".").rsplit(".", 1)[-1]
    if ":" not in host and NUMERIC_LABEL.fullmatch(last_label) and not is_dotted_quad(host):
        # Only plain dotted quads, so the browser and the resolver agree on the address.
        raise BlockedURL(f"{host} is an unusual form of IP address")
    try:
        infos = resolve(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        raise BlockedURL(f"{host} doesn't resolve") from None
    addresses = sorted({info[4][0] for info in infos})
    for address in addresses:
        if not public_address(address):
            raise BlockedURL(f"{host} resolves to a non-public address ({address})")
    return addresses


def public_address(text):
    """True for a public unicast address. `is_global` rules out loopback, private,
    link-local, carrier-grade NAT, and reserved ranges, but counts multicast as global."""
    ip = ipaddress.ip_address(text.split("%")[0])  # drop an IPv6 zone such as "%en0"
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 is 127.0.0.1
    elif ip in NAT64:
        ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.is_global and not ip.is_multicast


def is_dotted_quad(host):
    try:
        return str(ipaddress.IPv4Address(host)) == host
    except ValueError:
        return False
