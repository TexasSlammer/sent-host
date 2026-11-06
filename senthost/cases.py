"""The case battery: tricky authorities and explicit Host header values.

Two delivery modes:

- url:      the client is handed a URL and I capture the Host header it
            derives from that URL, as seen on the wire.
- override: the client is asked to set the Host header explicitly (where its
            API allows it) and I capture what actually gets sent.

Every case is observational. The matrix does not decide what is correct; it
records behavior per client version. Upstream filings happen only when a
recorded behavior is dangerous, and only through the disclosure route the
affected project documents.
"""

import urllib.parse


def punycode(host: str) -> str:
    return host.encode("idna").decode("ascii")


CASES = [
    # baselines ------------------------------------------------------------
    dict(id="H01", mode="url", url="http://localhost:8321/h01",
         note="baseline: plain host with port"),
    dict(id="H02", mode="url", url="http://LOCALHOST:8321/h02",
         note="uppercase host input"),
    dict(id="H03", mode="override", host="localhost:8321",
         note="baseline: explicit override, well-formed value"),

    # userinfo in the authority ---------------------------------------------
    dict(id="H04", mode="url", url="http://user:pass@localhost:8321/h04",
         note="credentials in the URL; the Host must still point at localhost"),
    dict(id="H05", mode="url", url="http://localhost:@evil.com:8321/h05",
         note="the shape behind the MCP python-sdk finding: empty password, then @evil.com"),
    dict(id="H06", mode="url", url="http://user@evil.com@localhost:8321/h06",
         note="two @ signs: which part is userinfo and which is the host?"),
    dict(id="H07", mode="override", host="localhost:@evil.com",
         note="explicit override carrying userinfo"),
    dict(id="H08", mode="override", host="localhost:0@evil.com",
         note="override with a port-looking prefix, then userinfo"),

    # numeric host tricks ----------------------------------------------------
    dict(id="H09", mode="url", url="http://0177.0.0.1:8321/h09",
         note="octal for 127.0.0.1; resolvers and parsers disagree"),
    dict(id="H10", mode="url", url="http://2130706433:8321/h10",
         note="decimal integer for 127.0.0.1"),
    dict(id="H11", mode="url", url="http://127.1:8321/h11",
         note="short form for 127.0.0.1"),

    # host name edge cases ---------------------------------------------------
    dict(id="H12", mode="url", url="http://localhost.:8321/h12",
         note="trailing dot: absolute FQDN"),
    dict(id="H13", mode="url", url="http://%6Cocalhost:8321/h13",
         note="percent-encoded first letter of localhost"),
    dict(id="H14", mode="url", url="http://löcalhost:8321/h14",
         note="IDN input; punycode form is " + punycode("löcalhost")),
    dict(id="H15", mode="url", url="http://under_score:8321/h15",
         note="underscore: invalid per RFC but accepted by many resolvers"),

    # IPv6 -------------------------------------------------------------------
    dict(id="H16", mode="url", url="http://[::1]:8321/h16",
         note="baseline IPv6 literal"),
    dict(id="H17", mode="url", url="http://[::1%25lo]:8321/h17",
         note="IPv6 with a zone id (Linux loopback form)"),

    # port edge cases ----------------------------------------------------------
    dict(id="H18", mode="url", url="http://localhost:/h18",
         note="empty port after the colon"),
    dict(id="H19", mode="url", url="http://localhost:0/h19",
         note="port zero"),
    dict(id="H20", mode="url", url="http://localhost:99999/h20",
         note="port above 65535"),
    dict(id="H21", mode="url", url="http://localhost:۸۰۸۰/h21",
         note="non-ASCII digits; a port must be ASCII digits per RFC 3986"),

    # messy override values that should be refused somewhere ------------------
    dict(id="H22", mode="override", host="localhost ",
         note="trailing space in the header value"),
    dict(id="H23", mode="override", host="localhost:abc",
         note="port that is not a number"),
    dict(id="H24", mode="override", host="localhost\r\nX-Injected: yes",
         note="CRLF injection attempt through the Host value"),
    dict(id="H25", mode="override", host="",
         note="empty Host value"),
    dict(id="H26", mode="override", host="localhost:۸۰۸۰",
         note="non-ASCII digits via override"),
]

# url-mode cases get the case id as their path so every request can be paired
# with its server-side log entry even when no extra header can be set (the
# browser cases, where a custom header would change how fetch behaves).
for _c in CASES:
    if _c["mode"] == "url":
        _p = urllib.parse.urlsplit(_c["url"])
        _c["url"] = urllib.parse.urlunsplit(
            (_p.scheme, _p.netloc, "/" + _c["id"].lower(), "", "")
        )


def loopback_safe(url: str) -> bool:
    """True when fetching url can only touch loopback by construction.

    Used by clients whose DNS resolution I cannot pin from outside (Node
    fetch, Chromium fetch): those clients fetch nothing whose parsed host is
    not exactly one of these, and record the parse result instead.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.hostname in ("localhost", "127.0.0.1", "::1")
        and (port is None or port == 8321)
    )
