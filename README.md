# sent-host

What does an HTTP client actually put in the Host header when the URL is weird, or when you set the header yourself?

This repo answers that empirically. A loopback server records every request's raw wire headers before any application code runs. A battery of 26 tricky inputs (userinfo forms, numeric IP spellings, trailing dots, percent-encoded labels, non-ASCII digits, CRLF injection attempts, and more) goes through seven real clients: httpx, requests, aiohttp, urllib, curl, Node, and Chromium. The full matrix is committed here per client version, and CI re-runs it on every push, so any client release that changes wire behavior shows up as a diff in this repo.

## Why

I built the first version of this harness while verifying a Host header finding in the Model Context Protocol Python SDK: its DNS rebinding protection middleware accepted values like `Host: localhost:@evil.com` because the allowlist did a raw prefix match. The middleware bug was only half the story. The other half is the question this repo exists for: which clients can even put such a value on the wire? That turned out to have no single public answer I could cite, so I turned the harness into a project of its own.

The answer, it turns out, is "more clients than you'd expect, in more ways than you'd expect."

## Headline results

Snapshot of 2026-11-06, exact values and case IDs in [results/](results/):

- **The Python standard library sends URL credentials in the Host header.** For `http://user:pass@localhost:8321/`, urllib sends `Host: user:pass@localhost:8321` (H04). For `http://localhost:@evil.com:8321/`, it sends `Host: localhost:@evil.com:8321` (H05) and for the double-@ form it sends the whole thing verbatim (H06). Every other tested client strips userinfo from the authority or refuses the URL outright. A server allowlisting `localhost` will not match what urllib sends, and what urllib sends is not a valid authority under RFC 3986.
- **curl lets a header value smuggle more headers.** Setting `Host: localhost\r\nX-Injected: yes` through `-H` arrives as two headers, `host: localhost` and `x-injected: yes` (H24, visible in the recorded server-side header set). All four Python clients refuse CRLF in header values outright.
- **httpx and aiohttp silently convert non-ASCII digit ports.** `http://localhost:۸۰۸۰/` (Arabic-Indic digits) parses as port 8080 and both clients connect to port 8080 (H21; aiohttp's own error message names `localhost:8080`). requests, urllib, curl, Node and Chromium all reject non-ASCII digits, as RFC 3986 requires.
- **Numeric IP spellings reach the server verbatim from Python clients.** `http://2130706433:8321/` arrives as `Host: 2130706433:8321` and `http://127.1:8321/` arrives as `Host: 127.1:8321` from requests, aiohttp and urllib (H10, H11). httpx refuses the octal form `0177.0.0.1` but forwards the decimal and short forms unchanged (H09). curl and Chromium normalize all three to `127.0.0.1` before sending. A Host allowlist that compares strings sees three different values for the same machine.
- **Percent-encoded host labels stay percent-encoded in httpx and aiohttp.** `http://%6Cocalhost:8321/` arrives as `Host: %6cocalhost:8321` (H13). requests, urllib, curl and Chromium decode to `localhost`.
- **Non-ASCII bytes go on the wire from curl and aiohttp.** An override value `Host: localhost:۸۰۸۰` is transmitted as raw UTF-8 bytes by curl, and aiohttp does the same in URL-derived form (H26). httpx, requests and urllib fail at Latin-1 header encode time instead.
- **Case handling splits the field.** For `http://LOCALHOST:8321/`, urllib and curl send `Host: LOCALHOST:8321` while every other client lowercases it (H02).
- **IDN handling splits too.** urllib sends raw non-ASCII `löcalhost` bytes; httpx, requests, aiohttp and curl all punycode to `xn--lcalhost-n4a` (H14).
- **The receiving side is fragile as well.** `Host: localhost:abc` gets a 500 from uvicorn plus Starlette (H23).

None of this is a vulnerability claim by itself. It is a record of what actually happens on the wire, which is the evidence you need before you can argue about what a Host allowlist should compare against. See [filings/](filings/) for how a recorded behavior becomes an upstream report.

## How it works

1. **Server.** A Starlette echo app wrapped in a raw ASGI logger. The logger records each request's full header set and final status before the app runs, including requests the app answers with 500. The echo endpoint reports how Starlette interpreted the request afterwards.
2. **Cases.** 26 inputs in two delivery modes. `url` mode hands a client a URL and captures the Host it derives. `override` mode asks the client to set the Host header explicitly, where the client API allows it.
3. **Clients.** httpx, requests, aiohttp, urllib, curl, Node and Chromium. Where the client exposes its own URL parser (httpx, urllib3, yarl, Node), the parse result is recorded next to the wire value, so you can see where a divergence was decided.
4. **Pairing.** Every request carries a unique `X-Case-Id-<client>` header (browser requests are paired by path), so wire values come from the server's raw log rather than from what the client library claims it sent.

### Isolation

Everything stays on loopback, enforced per client:

- Python clients run under a process-local `getaddrinfo` override that pins every hostname to `127.0.0.1` / `::1`. IP literals pass through untouched, and the server binds both stacks so `[::1]` requests are real.
- aiohttp is pinned to its `ThreadedResolver` so it cannot escape through a c-ares resolver that bypasses `getaddrinfo`.
- curl runs with `--resolve` entries covering every spelling of each hostname (raw, percent-decoded, punycode, with and without trailing dot).
- Node and Chromium fetch nothing whose parsed host is not exactly `localhost`, `127.0.0.1` or `::1`. Chromium also aborts every request that would leave the machine before a packet is sent, and records the headers the browser had prepared.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium        # optional, enables the browser column
python -m senthost.matrix
pytest -q                          # sanity checks
```

Results land in `results/` as JSON plus a markdown summary. Everything runs on `127.0.0.1`; no external traffic.

## Tested versions

The committed snapshot was produced on: Python 3.12.16, httpx 0.28.1, requests 2.32.5 (urllib3 2.6.3), aiohttp 3.13.3 (yarl 1.23.0), urllib, curl 8.14.1, Node v24.22.2, Chromium via Playwright 1.57.0, uvicorn 0.44.0, Starlette 0.50.0, h11 0.16.0. Client versions are recorded in every results file, because every conclusion here is a statement about a version, not about a project forever.

## Limitations

- HTTP/1.1 only. No h2, no HTTPS interception, no proxy chains.
- Default client configurations. Some clients can be configured into different behavior; that is out of scope until someone needs it.
- The Host header is the focus. Origin and other derived headers are recorded but not yet systematically probed.
- Chromium and Node can only do `url` mode. Neither API allows a raw Host override, which is itself a fact worth knowing.

## Filings

`filings/TEMPLATE.md` is the template I use when a matrix row shows behavior that is dangerous rather than merely divergent. The rule I hold myself to: a filing only goes out after re-verifying the behavior against the latest release of the affected client, and through whatever disclosure channel that project documents. Filed reports will be listed here with their outcomes.

## License

MIT. See [LICENSE](LICENSE).
