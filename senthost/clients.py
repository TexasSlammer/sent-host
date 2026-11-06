"""Client runners. Every runner returns a normalized observation dict:

    {
      "client": name,
      "case": case id,
      "mode": "url" | "override",
      "status": int | None,         # HTTP status from the loopback server
      "client_error": str | None,   # parse or refusal error (a refusal is data)
      "client_parse": dict | None,  # what the client's own URL parser produced
      "skipped": str | None,        # why this client could not participate
    }

The Host value that actually went on the wire comes from the server-side raw
log, paired on X-Case-Id where the client allows a custom header, and on the
request path otherwise. Nothing here talks to anything but 127.0.0.1.
"""

import asyncio
import ipaddress
import json
import os
import re
import socket
import subprocess
import urllib.parse
from contextlib import contextmanager

import httpx
import requests

SERVER_PORT = int(os.environ.get("SENTHOST_PORT", "8321"))


# ---------------------------------------------------------------- isolation


@contextmanager
def loopback_dns():
    """Pin every hostname this process resolves to 127.0.0.1 (IPv6: ::1).

    This is the isolation guarantee for the Python clients in url mode: no
    socket can target anything but loopback, and it doubles as a faithful
    DNS rebinding simulation, since the client parses the URL normally and
    DNS answers loopback for everything.

    IP literals pass through untouched. Rewriting them would fabricate
    behavior: a client that connects to [::1] must actually reach ::1, which
    is why the matrix runs the server on both stacks.
    """
    real = socket.getaddrinfo

    def patched(host, port, *args, **kwargs):
        try:
            ipaddress.ip_address(host)
            return real(host, port, *args, **kwargs)
        except (ValueError, TypeError):
            pass
        family = args[0] if args else kwargs.get("family", 0) or 0
        if family == socket.AF_INET6:
            return [(
                socket.AF_INET6, socket.SOCK_STREAM, 6, "",
                ("::1", port if isinstance(port, int) else 0, 0, 0),
            )]
        return [(
            socket.AF_INET, socket.SOCK_STREAM, 6, "",
            ("127.0.0.1", port if isinstance(port, int) else 0),
        )]

    socket.getaddrinfo = patched
    try:
        yield
    finally:
        socket.getaddrinfo = real


def _curl_resolve_keys(hostname: str) -> list:
    """Every plausible spelling curl might resolve for this hostname.

    curl matches --resolve entries literally against the host it derived, and
    it may percent-decode or punycode-convert first. Pinning all spellings is
    what keeps curl from doing real DNS for any case.
    """
    keys = {hostname}
    keys.add(urllib.parse.unquote(hostname))
    keys.add(hostname.rstrip(".") + ".")
    keys.add(hostname.rstrip("."))
    try:
        keys.add(hostname.encode("idna").decode("ascii"))
    except (UnicodeError, ValueError):
        pass
    return [k for k in keys if k]


# ---------------------------------------------------------------- server log


def read_server_log(path: str) -> dict:
    """Pair request and response log entries into one dict per case."""
    pairs = {}
    pending_cid = None
    pending_req = None
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return pairs
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("phase") == "request":
            headers = entry.get("headers", {})
            pending_cid = headers.get("x-case-id") or "path:" + entry.get("path", "")
            pending_req = entry
        elif entry.get("phase") == "response" and pending_cid:
            pairs[pending_cid] = {
                "sent_host": (pending_req or {}).get("headers", {}).get("host"),
                "status": entry.get("status"),
                "headers": (pending_req or {}).get("headers", {}),
            }
            pending_cid, pending_req = None, None
    return pairs


# ------------------------------------------------------------ python clients


def _url_target(case: dict) -> str:
    return f"http://127.0.0.1:{SERVER_PORT}/override"


def _httpx_parse(url: str):
    u = httpx.URL(url)
    return {"host": u.host, "port": u.port, "userinfo": bool(u.userinfo)}


def _urllib3_parse(url: str):
    from urllib3.util import parse_url

    p = parse_url(url)
    return {"host": p.host, "port": p.port, "userinfo": p.auth is not None}


def _yarl_parse(url: str):
    from yarl import URL

    u = URL(url)
    return {"host": u.host, "port": u.port, "userinfo": u.user is not None}


def _urlsplit_parse(url: str):
    parts = urllib.parse.urlsplit(url)
    return {"host": parts.hostname, "port": parts.port,
            "userinfo": parts.username is not None}


def run_httpx(case: dict) -> dict:
    out = {"client_parse": None}
    if case["mode"] == "override":
        with httpx.Client(timeout=6.0) as c:
            r = c.get(_url_target(case), headers={
                "Host": case["host"],
                "X-Case-Id": f"{case['id']}-httpx",
            })
    else:
        out["client_parse"] = _httpx_parse(case["url"])
        with loopback_dns(), httpx.Client(timeout=6.0) as c:
            r = c.get(case["url"], headers={"X-Case-Id": f"{case['id']}-httpx"})
    out["status"] = r.status_code
    return out


def run_requests(case: dict) -> dict:
    cid = f"{case['id']}-requests"
    parse = None
    if case["mode"] == "override":
        r = requests.get(_url_target(case), headers={
            "Host": case["host"], "X-Case-Id": cid,
        }, timeout=6.0)
    else:
        try:
            parse = _urllib3_parse(case["url"])
        except Exception as exc:
            return {"client_parse": None,
                    "client_error": f"parse_url refused: {exc}"[:180]}
        with loopback_dns():
            r = requests.get(case["url"], headers={"X-Case-Id": cid}, timeout=6.0)
    return {"status": r.status_code, "client_parse": parse}


def run_aiohttp(case: dict) -> dict:
    import aiohttp

    cid = f"{case['id']}-aiohttp"

    async def _run():
        resolver = aiohttp.resolver.ThreadedResolver()
        connector = aiohttp.TCPConnector(resolver=resolver)
        async with aiohttp.ClientSession(
            headers={"X-Case-Id": cid},
            skip_auto_headers=("User-Agent",),
            connector=connector,
        ) as s:
            if case["mode"] == "override":
                async with s.get(_url_target(case),
                                 headers={"Host": case["host"]}) as resp:
                    return {"status": resp.status, "client_parse": None}
            async with s.get(case["url"]) as resp:
                return {"status": resp.status}

    if case["mode"] == "url":
        try:
            parse = _yarl_parse(case["url"])
        except Exception as exc:
            return {"client_parse": None,
                    "client_error": f"yarl refused: {exc}"[:180]}
        with loopback_dns():
            out = asyncio.run(_run())
        out["client_parse"] = parse
        return out
    return asyncio.run(_run())


def run_urllib(case: dict) -> dict:
    import urllib.request

    cid = f"{case['id']}-urllib"
    if case["mode"] == "override":
        req = urllib.request.Request(_url_target(case), headers={
            "Host": case["host"], "X-Case-Id": cid,
        })
    else:
        try:
            parse = _urlsplit_parse(case["url"])
        except Exception as exc:
            return {"client_parse": None,
                    "client_error": f"urlsplit refused: {exc}"[:180]}
        req = urllib.request.Request(case["url"], headers={"X-Case-Id": cid})
    if case["mode"] == "url":
        with loopback_dns():
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                return {"status": resp.status, "client_parse": parse}
    with urllib.request.urlopen(req, timeout=6.0) as resp:
        return {"status": resp.status, "client_parse": None}


# ------------------------------------------------------------------- curl


def run_curl(case: dict) -> dict:
    base = [
        "curl", "-sS", "-v", "-o", "/dev/null", "--max-time", "8",
        "-H", f"X-Case-Id: {case['id']}-curl",
    ]
    if case["mode"] == "override":
        args = base + ["-H", f"Host: {case['host']}",
                       _url_target(case)]
    else:
        parts = urllib.parse.urlsplit(case["url"])
        host = parts.hostname
        if host is None:
            return {"client_error": "no parsable hostname", "client_parse": None,
                    "skipped": None}
        resolves = []
        for k in _curl_resolve_keys(host):
            resolves += ["--resolve", f"{k}:{SERVER_PORT}:127.0.0.1"]
        args = base + resolves + [case["url"]]
    proc = subprocess.run(args, capture_output=True, text=True, timeout=25)
    blob = proc.stdout + proc.stderr
    sent_host_local, status = None, None
    for line in blob.splitlines():
        m = re.match(r"> Host:\s*(.+)", line.strip())
        if m:
            sent_host_local = m.group(1).strip()
        m = re.match(r"< HTTP/([\d.]+)\s+(\d+)", line.strip())
        if m:
            status = int(m.group(2))
    out = {"status": status, "client_parse": None,
           "sent_host_local": sent_host_local}
    if proc.returncode != 0 and status is None:
        errs = [ln for ln in blob.splitlines() if "curl:" in ln]
        out["client_error"] = (errs[-1] if errs else blob[-160:]).strip()
    return out


# -------------------------------------------------------------------- node


NODE_PARSE_SCRIPT = (
    "try { const u = new URL(process.argv[1]);"
    "console.log(JSON.stringify({ok: true, host: u.host, hostname: u.hostname,"
    " port: u.port, username: u.username, password: u.password}));"
    "} catch (e) { console.log(JSON.stringify({ok: false,"
    " error: String(e && e.message || e).slice(0, 140)})); }"
)


def run_node(case: dict) -> dict:
    if case["mode"] != "url":
        return {"skipped": "node fetch cannot override the Host header"}
    p = subprocess.run(["node", "-e", NODE_PARSE_SCRIPT, case["url"]],
                       capture_output=True, text=True, timeout=15)
    if p.returncode != 0 or not p.stdout.strip():
        msg = (p.stderr.strip().splitlines() or ["no output"])[-1][:140]
        return {"client_error": f"node URL parse failed: {msg}", "client_parse": None}
    parse = json.loads(p.stdout.strip().splitlines()[-1])
    if not parse.get("ok"):
        return {"client_error": "URL parse threw: " + parse.get("error", ""),
                "client_parse": None}
    from .cases import loopback_safe
    if not loopback_safe(case["url"]):
        return {"client_parse": parse,
                "skipped": "fetch skipped by isolation policy (host outside the loopback set)"}
    fetch_js = (
        "fetch(process.argv[1], {cache: 'no-store', headers: {'X-Case-Id':"
        " process.argv[2]}}).then(r => r.text().then(()=>"
        " console.log(JSON.stringify({ok: true, status: r.status}))))"
        ".catch(e => console.log(JSON.stringify({ok: false,"
        " error: String(e && e.message || e).slice(0, 140)})));"
    )
    p2 = subprocess.run(
        ["node", "-e", fetch_js, case["url"], f"{case['id']}-node"],
        capture_output=True, text=True, timeout=15)
    lines = p2.stdout.strip().splitlines()
    if not lines:
        return {"client_parse": parse,
                "client_error": (p2.stderr.strip().splitlines() or ["no output"])[-1][:140]}
    result = json.loads(lines[-1])
    return {
        "client_parse": parse,
        "status": result.get("status"),
        "client_error": None if result.get("ok") else result.get("error"),
    }


# ---------------------------------------------------------------- chromium


CHROME_PAGE_HTML = """
<!doctype html><html><body><script>
window.__done = false;
window.__results = {};
(async () => {
  const targets = %s;
  for (const [cid, url] of targets) {
    try {
      const r = await fetch(url, {mode: 'no-cors', cache: 'no-store'});
      window.__results[cid] = 'fetch-status-' + r.status;
    } catch (e) {
      window.__results[cid] = 'fetch-error: ' + String(e && e.message || e).slice(0, 90);
    }
    await new Promise(res => setTimeout(res, 120));
  }
  window.__done = true;
})();
</script></body></html>
"""


def run_chromium_batch(url_cases: list) -> dict:
    """Run every url-mode case in one headless Chromium session.

    A route handler inspects each outgoing request: loopback targets are
    forwarded to the local server (which records the wire headers), anything
    else is aborted before a packet leaves the machine, and the headers the
    browser had prepared are captured instead.
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    import time as _time

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {c["id"]: {"skipped": "playwright not installed"} for c in url_cases}

    targets = [[c["id"], c["url"]] for c in url_cases]
    page_html = CHROME_PAGE_HTML % json.dumps(targets)

    class AttackerPage(BaseHTTPRequestHandler):
        def do_GET(self):
            body = page_html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    page_srv = ThreadingHTTPServer(("127.0.0.1", 9999), AttackerPage)
    threading.Thread(target=page_srv.serve_forever, daemon=True).start()

    route_records = []
    out = {c["id"]: {} for c in url_cases}
    try:
        import glob
        exe = glob.glob(os.path.expanduser(
            "~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome"))
        exe += glob.glob(os.path.expanduser(
            "~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome"))
        if not exe:
            return {c["id"]: {"skipped": "chromium binary not found"} for c in url_cases}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=exe[0])
            page = browser.new_page()

            def handle_route(route):
                req = route.request
                url = req.url
                parts = urllib.parse.urlsplit(url)
                host = (parts.hostname or "").lower()
                route_records.append({
                    "url": url,
                    "host": host,
                    "port": parts.port,
                    "headers": {k.lower(): v for k, v in req.headers.items()},
                })
                if host in ("127.0.0.1", "localhost", "::1") and parts.port in (SERVER_PORT, 9999):
                    route.continue_()
                else:
                    route.abort("aborted")

            page.route("**/*", handle_route)
            page.goto("http://127.0.0.1:9999/attacker.html")
            page.wait_for_function("window.__done === true", timeout=60000)
            in_page = page.evaluate("window.__results")
            browser.close()
    finally:
        page_srv.shutdown()

    for rec in route_records:
        for c in url_cases:
            if rec["url"].rstrip("/").endswith("/" + c["id"].lower()):
                out[c["id"]]["prepared_host"] = rec["headers"].get("host")
                out[c["id"]]["forwarded"] = rec["host"] in ("127.0.0.1", "localhost", "::1") \
                    and rec["port"] == SERVER_PORT
                break
    for c in url_cases:
        res = (in_page or {}).get(c["id"])
        if res:
            if res.startswith("fetch-status-"):
                out[c["id"]]["status"] = int(res.rsplit("-", 1)[1])
            else:
                out[c["id"]]["client_error"] = res
        elif "prepared_host" not in out[c["id"]]:
            out[c["id"]]["skipped"] = "request never reached the network stack"
    return out
