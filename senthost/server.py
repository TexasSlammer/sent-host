"""Loopback echo server that records the raw headers every request carries.

An outer ASGI wrapper records each request's full header set and final status
before any application code runs, including requests a downstream gate would
reject. The echo endpoint then reports how Starlette interpreted the request.

Everything binds to 127.0.0.1. No external traffic.
"""

import json
import os
import time

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

LOG_PATH = os.environ.get("SENTHOST_LOG", "/tmp/senthost_server.log")
PORT = int(os.environ.get("SENTHOST_PORT", "8321"))
HOST = os.environ.get("SENTHOST_HOST", "127.0.0.1")


def _log(entry: dict) -> None:
    entry["ts"] = round(time.time(), 3)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


class RawRequestLogger:
    """Outermost ASGI wrapper: raw headers and final status for every request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        final_status = {"code": None}

        async def send_wrap(message):
            if message["type"] == "http.response.start":
                final_status["code"] = message["status"]
            await send(message)

        _log({
            "phase": "request",
            "method": scope["method"],
            "path": scope["path"],
            "headers": {
                k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]
            },
        })
        try:
            await self.app(scope, receive, send_wrap)
        except Exception:
            # The application raised and uvicorn will emit a bare 500 outside
            # this wrapper. Log it anyway so request/response pairing holds.
            _log({"phase": "response", "path": scope["path"], "status": 500})
            raise
        _log({"phase": "response", "path": scope["path"], "status": final_status["code"]})


async def echo(request: Request):
    return JSONResponse({
        "raw_host_header": request.headers.get("host"),
        "url_host": request.url.hostname,
        "url_port": request.url.port,
        "base_url": str(request.base_url),
    })


app = RawRequestLogger(Starlette(routes=[Route("/{p:path}", echo, methods=["GET", "POST"])]))

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning", access_log=False)
