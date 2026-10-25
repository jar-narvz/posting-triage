"""public_url(): decision 9's check on the URL the API is asked to fetch.
A fake resolver stands in for DNS; the last test uses the real one, which
answers numeric hosts and localhost without the network."""

import socket

import pytest

from posting_triage.urlguard import BlockedURL, public_address, public_host, public_url

PUBLIC = "93.184.215.14"


def resolver(table):
    """A getaddrinfo stand-in: hostname -> list of addresses."""
    def resolve(host, port, proto=0):
        if host not in table:
            raise socket.gaierror(socket.EAI_NONAME, "not found")
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, proto, "", (a, port))
                for a in table[host]]
    return resolve


@pytest.mark.parametrize("url", [
    "https://job-boards.greenhouse.io/acme/jobs/123",
    "http://jobs.example.com/swe",
    "https://jobs.example.com:443/swe",
    "https://JOBS.example.com./swe",
])
def test_public_urls_pass_unchanged(url):
    assert public_url(url, resolver({"job-boards.greenhouse.io": [PUBLIC], "jobs.example.com": [PUBLIC],
                                     "jobs.example.com.": [PUBLIC]})) == url


@pytest.mark.parametrize("address", [
    "127.0.0.1",        # loopback
    "10.0.0.5",         # private
    "172.16.0.1",
    "192.168.1.1",
    "169.254.169.254",  # EC2 metadata
    "169.254.170.2",    # ECS / App Runner container credentials
    "100.64.0.1",       # carrier-grade NAT
    "0.0.0.0",
    "224.0.0.1",        # multicast (is_global alone lets this through)
    "ff02::1",
    "::1",
    "fd00::1",          # IPv6 unique-local
    "fe80::1",          # IPv6 link-local
    "::ffff:127.0.0.1",  # IPv4-mapped
    "64:ff9b::7f00:1",  # NAT64 around 127.0.0.1
])
def test_a_name_that_resolves_to_a_non_public_address_is_blocked(address):
    with pytest.raises(BlockedURL, match="non-public"):
        public_url("https://innocent.example/", resolver({"innocent.example": [address]}))


def test_one_private_address_among_public_ones_is_enough_to_block():
    with pytest.raises(BlockedURL, match="10.0.0.5"):
        public_url("https://mixed.example/", resolver({"mixed.example": [PUBLIC, "10.0.0.5"]}))


@pytest.mark.parametrize("url, reason", [
    ("ftp://example.com/x", "http and https"),
    ("file:///etc/passwd", "http and https"),
    ("javascript:alert(1)", "http and https"),
    ("https://user:pw@example.com/", "username or password"),
    ("https://example.com@169.254.169.254/", "username or password"),
    ("https:///jobs", "no hostname"),
    ("https://example.com:8080/", "ports 80 and 443"),
    ("https://example.com:99999/", "port is not a number"),
    ("https://nowhere.example/", "doesn't resolve"),
])
def test_bad_urls_are_blocked_with_a_reason(url, reason):
    with pytest.raises(BlockedURL, match=reason):
        public_url(url, resolver({"example.com": [PUBLIC]}))


@pytest.mark.parametrize("host", ["2130706433", "0x7f.1", "127.1", "0177.0.0.1", "0x7f000001", "1.2.3.04"])
def test_unusual_ip_forms_are_blocked_before_resolving(host):
    # 0177.0.0.1 is the trap: macOS's resolver reads 177.0.0.1 (public), Chromium reads octal 127.0.0.1.
    with pytest.raises(BlockedURL, match="unusual form"):
        public_url(f"http://{host}/", resolver({}))


def test_public_host_returns_the_addresses_it_checked():
    # The proxy connects to these, so a second DNS answer can't swap in a private address.
    assert public_host("multi.example", 443, resolver({"multi.example": ["2606:4700::1111", PUBLIC]})) == [
        "2606:4700::1111", PUBLIC]


def test_a_public_dotted_quad_passes():
    assert public_url(f"http://{PUBLIC}/", resolver({PUBLIC: [PUBLIC]}))


def test_ipv6_literals_are_checked_by_address():
    with pytest.raises(BlockedURL, match="non-public"):
        public_url("http://[::1]/", resolver({"::1": ["::1"]}))


@pytest.mark.parametrize("address, public", [
    ("8.8.8.8", True), ("2606:4700::1111", True), ("fe80::1%en0", False), ("::ffff:8.8.8.8", True),
])
def test_public_address(address, public):
    assert public_address(address) is public


@pytest.mark.parametrize("url", ["http://localhost/", "http://127.0.0.1/", "http://[::1]/"])
def test_the_real_resolver_blocks_loopback(url):
    with pytest.raises(BlockedURL):
        public_url(url)
