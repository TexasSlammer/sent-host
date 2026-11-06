"""Orchestrator: start the loopback server, run every case through every
client, pair the observations with the server-side raw log, and write
results/ as JSON plus a markdown summary.

Usage:  python -m senthost.matrix
"""

import importlib.metadata as md
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .cases import CASES
from . import clients

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RESULTS = ROOT / "results"
SERVER = HERE / "server.py"
LOG = os.environ.get("SENTHOST_LOG", "/tmp/senthost_server.log")
PORT = int(os.environ.get("SENTHOST_PORT", "8321"))

CLIENTS = [
    ("httpx", clients.run_httpx, {"url", "override"}, True),
    ("requests", clients.run_requests, {"url", "override"}, True),
    ("aiohttp", clients.run_aiohttp, {"url", "override"}, True),
    ("urllib", clients.run_urllib, {"url", "override"}, True),
    ("curl", clients.run_curl, {"url", "override"}, True),
    ("node", clients.run_node, {"url"}, True),
    ("chromium", None, {"url"}, False),
]


def wait_port(port: int, timeout: float = 20.0) -> bool:
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def versions() -> dict:
    out = {"python": sys.version.split()[0]}
    for pkg in ("httpx", "requests", "aiohttp", "uvicorn", "starlette", "h11",
                "playwright", "urllib3", "yarl"):
        try:
            out[pkg] = md.version(pkg)
        except Exception:
            out[pkg] = "absent"
    for tool, cmd in (("curl", ["curl", "--version"]), ("node", ["node", "--version"])):
        try:
            out[tool] = subprocess.run(cmd, capture_output=True, text=True,
                                       timeout=10).stdout.splitlines()[0]
        except Exception:
            out[tool] = "absent"
    return out


def safe_run(fn, case: dict) -> dict:
    try:
        return fn(case)
    except Exception as exc:
        return {"client_error": f"{type(exc).__name__}: {exc}"[:180]}


def cell(row: dict, width: int = 26) -> str:
    if row.get("sent_host") is not None:
        text = row["sent_host"] if row["sent_host"] != "" else "(empty)"
    elif row.get("sent_host_local") is not None:
        text = f"local-view: {row['sent_host_local']}"
    elif row.get("prepared_host") is not None:
        text = f"prepared (aborted): {row['prepared_host']}"
    elif row.get("client_error"):
        text = f"refused: {row['client_error']}"
    elif row.get("skipped"):
        text = f"skip: {row['skipped']}"
    else:
        text = "-"
    return text.replace("|", "\\|")[:width]


def write_summary(env: dict, rows: list, path: Path) -> None:
    by_key = {(r["client"], r["case"]): r for r in rows if "client" in r}
    client_names = [n for n, _, _, _ in CLIENTS]
    lines = [
        "# Summary",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "Cell values: what the server received on the wire (`sent_host`), what an "
        "aborted browser request had prepared (`prepared`), the client's own "
        "refusal (`refused`), or why the client did not participate (`skip`).",
        "",
    ]
    header = "| case | mode | input | " + " | ".join(client_names) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (3 + len(client_names)))
    for case in CASES:
        inputs = case.get("url") if case["mode"] == "url" else f"Host: {case['host']!r}"
        row_cells = []
        for name in client_names:
            r = by_key.get((name, case["id"]))
            row_cells.append(cell(r) if r else "-")
        lines.append(f"| {case['id']} | {case['mode']} | {case['note']} | "
                     + " | ".join(row_cells) + " |")
    lines.append("")
    lines.append("Full data with parse results, per-request raw headers and raw values: results/*.json")
    path.write_text("\n".join(lines))


def start_servers() -> tuple:
    """Start the echo server on IPv4 and, when available, IPv6 loopback."""
    import socket as _s
    procs = []
    has_v6 = False
    try:
        with _s.socket(_s.AF_INET6, _s.SOCK_STREAM) as s:
            s.bind(("::1", 0))
            has_v6 = True
    except OSError:
        pass
    if os.path.exists(LOG):
        os.remove(LOG)
    env = dict(os.environ, SENTHOST_PORT=str(PORT), SENTHOST_LOG=LOG)
    procs.append(subprocess.Popen(
        [sys.executable, str(SERVER)],
        env=dict(env, SENTHOST_HOST="127.0.0.1"),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ))
    if has_v6:
        procs.append(subprocess.Popen(
            [sys.executable, str(SERVER)],
            env=dict(env, SENTHOST_HOST="::1"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ))
    assert wait_port(PORT), "loopback server did not start on 127.0.0.1"
    if has_v6:
        assert wait_port6(PORT), "loopback server did not start on ::1"
    time.sleep(0.3)
    return procs, has_v6


def wait_port6(port: int, timeout: float = 20.0) -> bool:
    import socket as _s
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with _s.socket(_s.AF_INET6, _s.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(("::1", port))
                return True
        except OSError:
            time.sleep(0.2)
    return False

def run_all() -> Path:
    RESULTS.mkdir(exist_ok=True)
    env = versions()
    rows = []
    procs, has_v6 = start_servers()
    try:
        for name, fn, modes, sends_cid in CLIENTS:
            for case in CASES:
                if case["mode"] not in modes:
                    rows.append({"client": name, "case": case["id"],
                                 "mode": case["mode"],
                                 "skipped": f"{name} does not support this delivery mode"})
                    continue
                if name == "chromium":
                    continue
                obs = safe_run(fn, case)
                rows.append({"client": name, "case": case["id"],
                             "mode": case["mode"], **obs})
        url_cases = [c for c in CASES if c["mode"] == "url"]
        try:
            browser = clients.run_chromium_batch(url_cases)
        except Exception as exc:
            browser = {c["id"]: {"skipped": f"browser batch failed: {type(exc).__name__}"}
                       for c in url_cases}
        for case in url_cases:
            rows.append({"client": "chromium", "case": case["id"],
                         "mode": "url", **browser.get(case["id"], {})})
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        pairs = clients.read_server_log(LOG)

    for r in rows:
        key = None
        name = r.get("client")
        sends_cid = next((c for n, _, _, c in CLIENTS if n == name), None)
        if r.get("case") and sends_cid:
            key = f"{r['case']}-{name}"
        elif r.get("case"):
            key = "path:/" + r["case"].lower()
        pair = pairs.get(key)
        if pair:
            r["sent_host"] = pair.get("sent_host")
            r["server_headers"] = pair.get("headers", {})
            if r.get("status") is None:
                r["status"] = pair.get("status")
    out = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "environment": {**env, "ipv6_server": has_v6},
        "isolation": (
            "Python clients run under a process-local getaddrinfo override that "
            "pins every hostname to loopback, with IP literals passed through "
            "untouched. aiohttp is pinned to its ThreadedResolver so it cannot "
            "escape through a c-ares resolver. curl runs with --resolve entries "
            "for every spelling of each hostname. Node and Chromium only fetch "
            "URLs whose parsed host is exactly localhost, 127.0.0.1 or ::1, and "
            "Chromium aborts every request that would leave the machine before "
            "a packet is sent. No external traffic."
        ),
        "rows": rows,
    }


    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    json_path = RESULTS / f"sent-host-results-{stamp}.json"
    json_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    write_summary(env, rows, RESULTS / "summary.md")
    return json_path


if __name__ == "__main__":
    path = run_all()
    print(f"rows: {sum(1 for _ in json.loads(path.read_text())['rows'])}")
    print(f"saved -> {path}")
    print(f"saved -> {RESULTS / 'summary.md'}")
