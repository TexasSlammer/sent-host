"""Sanity checks for the case battery and isolation helpers.

These do not make network requests. They exist so that an accidental change
to the case semantics cannot slip through CI unnoticed.
"""

from senthost.cases import CASES, loopback_safe


def test_case_ids_are_unique():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))


def test_modes_are_valid():
    assert all(c["mode"] in ("url", "override") for c in CASES)


def test_url_cases_have_absolute_urls_with_unique_paths():
    import urllib.parse

    urls = [c["url"] for c in CASES if c["mode"] == "url"]
    paths = []
    for u in urls:
        parts = urllib.parse.urlsplit(u)
        assert parts.scheme == "http"
        assert parts.netloc
        paths.append(parts.path)
    assert len(paths) == len(set(paths))


def test_override_cases_define_host():
    for c in CASES:
        if c["mode"] == "override":
            assert isinstance(c["host"], str)


def test_the_crlf_case_stays_in_the_battery():
    # H24 is the most security-relevant case in the set. If someone removes
    # or rewrites it, CI should notice.
    crlf = [c for c in CASES if c["id"] == "H24"]
    assert len(crlf) == 1
    assert "\r\n" in crlf[0]["host"]


def test_loopback_safe_bounds_what_node_and_chromium_may_fetch():
    assert loopback_safe("http://localhost:8321/x")
    assert loopback_safe("http://127.0.0.1:8321/x")
    assert loopback_safe("http://[::1]:8321/x")
    assert not loopback_safe("http://evil.com:8321/x")
    assert not loopback_safe("http://localhost:@evil.com:8321/x")
    assert not loopback_safe("http://localhost.:8321/x")
    assert not loopback_safe("http://0177.0.0.1:8321/x")


def test_ip_literals_and_userinfo_shapes_survive_the_path_rewrite():
    # The path rewrite must not disturb the authority part of any url case.
    import urllib.parse

    for c in CASES:
        if c["mode"] != "url":
            continue
        parts = urllib.parse.urlsplit(c["url"])
        if c["id"] == "H05":
            assert "@" in parts.netloc
        if c["id"] == "H16":
            assert parts.hostname == "::1"
