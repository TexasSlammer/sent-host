# Methodology

This document explains how the matrix is produced, what every case is for, and what guarantees hold between the recorded values and reality. Read this before trusting, disputing, or extending any result.

## Pipeline

1. `python -m senthost.matrix` starts one or two echo servers (IPv4 loopback and, when the machine supports it, IPv6 loopback) on port 8321. The server is a Starlette app wrapped in a raw ASGI logger that writes one JSON line per request and per response to a log file. The log happens before application code, so nothing an app does can suppress or rewrite a record.
2. For every case and every client, the client makes its request and the runner records what it can observe client-side: HTTP status, its own URL parser's output where it has one, and any refusal (a refusal is data, not a failure of the harness).
3. The server log is paired back onto the observations by case id. Every runner tags its request with a unique `X-Case-Id-<client>` header, so the wire value in the results is what the server received, not what the client library claims. Chromium cannot set custom headers on a no-cors fetch, so browser requests are paired by unique path instead.
4. `results/sent-host-results-<date>.json` gets the full rows (including every raw server-side header set) and `results/summary.md` gets the human table.
5. CI runs the same thing on GitHub's runners and fails when committed results change without review. That converts client releases into reviewable diffs in this repo.

## Case catalog

Two delivery modes:

- **url**: the client is handed a URL; I capture the Host header it derives from the URL as seen on the wire.
- **override**: the client is asked to send an explicit Host value, where its API allows it. Node and Chromium cannot override, which is itself a documented difference.

| id | mode | input | what it probes |
|---|---|---|---|
| H01 | url | `http://localhost:8321/` | baseline |
| H02 | url | `http://LOCALHOST:8321/` | case preservation |
| H03 | override | `Host: localhost:8321` | baseline override |
| H04 | url | `http://user:pass@localhost:8321/` | userinfo handling |
| H05 | url | `http://localhost:@evil.com:8321/` | the MCP-python-sdk finding shape: empty password, then a second host |
| H06 | url | `http://user@evil.com@localhost:8321/` | two `@` signs: which part is userinfo? |
| H07 | override | `Host: localhost:@evil.com` | userinfo smuggled through an override |
| H08 | override | `Host: localhost:0@evil.com` | port-looking prefix, then userinfo |
| H09 | url | `http://0177.0.0.1:8321/` | octal for 127.0.0.1 |
| H10 | url | `http://2130706433:8321/` | decimal integer for 127.0.0.1 |
| H11 | url | `http://127.1:8321/` | short form for 127.0.0.1 |
| H12 | url | `http://localhost.:8321/` | trailing dot (absolute FQDN) |
| H13 | url | `http://%6Cocalhost:8321/` | percent-encoded host label |
| H14 | url | `http://löcalhost:8321/` | IDN input (punycode form `xn--lcalhost-n4a`) |
| H15 | url | `http://under_score:8321/` | underscore, invalid per RFC but accepted by resolvers |
| H16 | url | `http://[::1]:8321/` | IPv6 literal baseline |
| H17 | url | `http://[::1%25lo]:8321/` | IPv6 with zone id |
| H18 | url | `http://localhost:/` | empty port (means port 80 per WHATWG) |
| H19 | url | `http://localhost:0/` | port zero |
| H20 | url | `http://localhost:99999/` | port above 65535 |
| H21 | url | `http://localhost:۸۰۸۰/` | non-ASCII digit port |
| H22 | override | `Host: "localhost "` | trailing space in the value |
| H23 | override | `Host: localhost:abc` | non-numeric port in the header |
| H24 | override | `Host: "localhost\r\nX-Injected: yes"` | CRLF injection through the value |
| H25 | override | `Host: ""` | empty Host value |
| H26 | override | `Host: localhost:۸۰۸۰` | non-ASCII bytes through the header API |

Case ids are stable. New cases get new ids and never change the meaning of an old one, so results stay comparable across time.

## Parser capture

Where a client exposes its own URL parser, the matrix records what that parser produced next to the wire value:

- httpx: `httpx.URL` (host, port, userinfo present)
- requests: `urllib3.util.parse_url`
- aiohttp: `yarl.URL`
- urllib: `urllib.parse.urlsplit`
- Node: `new URL()`

curl's URL parser is internal, so curl rows carry wire behavior only. This separation matters: it shows whether a divergence was decided at parse time or at header-construction time. H04 and H05 are the clearest example: urllib's parser (urlsplit) produces the same host as everyone else, but its header construction pastes the full netloc into the Host header anyway.

## Isolation guarantees

No case may produce traffic to anything but loopback. Enforcement is per client, because each one resolves names differently:

- **Python clients** run under a process-local `socket.getaddrinfo` override that answers `127.0.0.1` (or `::1` for AF_INET6) for every hostname. IP literals are passed through to the real resolver untouched; rewriting them would fabricate client behavior. The server binds both `127.0.0.1` and `::1` so literal IPv6 requests are real end to end.
- **aiohttp** would use a c-ares based resolver when `aiodns` is installed, which bypasses `getaddrinfo` entirely. The harness pins it to `ThreadedResolver` explicitly, and `aiodns` is deliberately absent from requirements.
- **curl** runs with `--resolve` entries for every plausible spelling of each hostname: raw, percent-decoded, punycode, with and without trailing dot. This is belt and suspenders; without it, a case whose derived host does not match the resolve key would trigger real DNS.
- **Node** parses the URL first and fetches only when the parsed host is exactly `localhost`, `127.0.0.1` or `::1` on port 8321. Otherwise the parse result is recorded and the fetch is skipped, marked `fetch skipped by isolation policy`.
- **Chromium** runs behind a Playwright route handler that forwards loopback requests and aborts everything else before a packet leaves the machine, recording the headers the browser had prepared.

If any of these guarantees cannot be established in an environment, the affected rows are marked skipped rather than approximated.

## Versioning policy

Every results file embeds the full environment: interpreter version, every client library version, curl and Node versions, and whether the IPv6 server was up. A conclusion in the README is always a statement about a recorded version. When a client changes behavior, CI fails the drift check and the new results land as a reviewed commit, so the history of a client's wire behavior accumulates in this repo.

## Not goals

- This is not a fuzzer. The battery is hand-curated, each case exists because it distinguishes implementations, and results are deterministic per version.
- This is not an exploit tool. No case attacks a third party; everything runs against a local echo server.
- It does not try to decide what a client "should" send. The RFC and WHATWG references live in the filings template, and a filing is only written when a recorded behavior is dangerous, not merely divergent.
