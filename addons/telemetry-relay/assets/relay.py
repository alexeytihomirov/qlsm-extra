#!/usr/bin/env python3
"""Local HTTP telemetry relay on game VPS (stdlib only).

QLDS minqlx plugins POST to 127.0.0.1; relay forwards to ql-stats-hub upstream.
Config: ~/telemetry-relay.json (routes by hub Server.id in JSON body).
"""

from __future__ import annotations

import http.client
import json
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

CONFIG_PATH = os.environ.get(
    "QL_TELEMETRY_RELAY_CONFIG",
    os.path.expanduser("~/telemetry-relay.json"),
)
LISTEN_HOST = os.environ.get("QL_TELEMETRY_RELAY_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("QL_TELEMETRY_RELAY_PORT", "8190"))

VERSION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")


def _load_version() -> dict[str, str | None]:
    try:
        with open(VERSION_PATH, encoding="utf-8") as fh:
            raw = fh.read().strip()
    except OSError:
        return {"sha": None, "deployed_at": None}
    parts = raw.split(None, 1)
    sha = parts[0] if parts and parts[0] != "unknown" else None
    deployed_at = parts[1] if len(parts) > 1 and parts[1] != "unknown" else None
    return {"sha": sha, "deployed_at": deployed_at}


_VERSION = _load_version()

_config_lock = threading.Lock()
_config: dict[str, Any] = {
    "enabled": False,
    "token": "",
    "routes": {},
    "timeout_sec": 2.0,
}
_stats_lock = threading.Lock()
_stats: dict[str, Any] = {
    "telemetry_forwarded": 0,
    "item_events_forwarded": 0,
    "item_events_received": 0,
    "session_events_forwarded": 0,
    "session_events_received": 0,
    "telemetry_received": 0,
    "dropped_busy": 0,
    "dropped_no_route": 0,
    "queue_depth_max": 0,
    "forward_errors": 0,
    "last_forward_at": None,
    "last_error": None,
}
_telemetry_forwarder: "_StreamForwarder | None" = None
_items_forwarder: "_StreamForwarder | None" = None
_session_forwarder: "_StreamForwarder | None" = None


class _StreamForwarder:
    """Sequential forward queue — never drop under burst."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._lock = threading.Lock()
        self._forward_lock = threading.Lock()
        self._queue: list[dict[str, Any]] = []
        self._worker: threading.Thread | None = None

    def _forward_post(self, url: str, token: str, body: bytes, timeout: float) -> None:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "http").lower()
        host = parsed.hostname
        if not host:
            raise ValueError("invalid upstream url")
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        with self._forward_lock:
            if scheme == "https":
                conn = http.client.HTTPSConnection(host, port, timeout=timeout)
            else:
                conn = http.client.HTTPConnection(host, port, timeout=timeout)
            try:
                conn.request(
                    "POST",
                    path,
                    body=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {token}",
                        "Connection": "close",
                    },
                )
                resp = conn.getresponse()
                resp.read()
                if resp.status >= 400:
                    raise RuntimeError(f"upstream HTTP {resp.status}")
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def forward_now(
        self,
        *,
        url: str,
        token: str,
        body: bytes,
        timeout: float,
        counter_key: str,
        event_count: int = 1,
    ) -> None:
        """Blocking forward for low-volume item-events (ack only after upstream OK)."""
        self._forward_post(url, token, body, timeout)
        with _stats_lock:
            _stats[counter_key] = int(_stats.get(counter_key) or 0) + event_count
            _stats["last_forward_at"] = _utc_now()
            _stats["last_error"] = None

    def enqueue(
        self,
        *,
        url: str,
        token: str,
        body: bytes,
        timeout: float,
        counter_key: str,
    ) -> str:
        with self._lock:
            self._queue.append(
                {
                    "url": url,
                    "token": token,
                    "body": body,
                    "timeout": timeout,
                    "counter_key": counter_key,
                }
            )
            depth = len(self._queue)
            if depth > 1:
                with _stats_lock:
                    _stats["queue_depth_max"] = max(
                        int(_stats.get("queue_depth_max") or 0),
                        depth,
                    )
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._run,
                    name=f"ql-relay-{self._name}",
                    daemon=True,
                )
                self._worker.start()
        return "queued"

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._worker = None
                    return
                job = self._queue.pop(0)
            try:
                self._forward_post(job["url"], job["token"], job["body"], job["timeout"])
                with _stats_lock:
                    key = job["counter_key"]
                    _stats[key] = int(_stats.get(key) or 0) + 1
                    _stats["last_forward_at"] = _utc_now()
                    _stats["last_error"] = None
            except (http.client.HTTPException, OSError, RuntimeError, ValueError) as exc:
                retries = int(job.get("retries") or 0)
                if retries < 2:
                    job["retries"] = retries + 1
                    with self._lock:
                        self._queue.insert(0, job)
                        if self._worker is None or not self._worker.is_alive():
                            self._worker = threading.Thread(
                                target=self._run,
                                name=f"ql-relay-{self._name}",
                                daemon=True,
                            )
                            self._worker.start()
                    continue
                with _stats_lock:
                    _stats["forward_errors"] = int(_stats.get("forward_errors") or 0) + 1
                    _stats["last_error"] = str(exc)[:200]


def _telemetry_forwarder_get() -> _StreamForwarder:
    global _telemetry_forwarder
    if _telemetry_forwarder is None:
        _telemetry_forwarder = _StreamForwarder("telemetry")
    return _telemetry_forwarder


def _items_forwarder_get() -> _StreamForwarder:
    global _items_forwarder
    if _items_forwarder is None:
        _items_forwarder = _StreamForwarder("item-events")
    return _items_forwarder


def _session_forwarder_get() -> _StreamForwarder:
    global _session_forwarder
    if _session_forwarder is None:
        _session_forwarder = _StreamForwarder("session-events")
    return _session_forwarder


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config() -> None:
    global _config
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError:
        data = {}
    except json.JSONDecodeError as exc:
        with _stats_lock:
            _stats["last_error"] = f"config json: {exc}"[:200]
        data = {}
    if not isinstance(data, dict):
        data = {}
    routes = data.get("routes") if isinstance(data.get("routes"), dict) else {}
    cleaned: dict[str, dict[str, str]] = {}
    for key, row in routes.items():
        if not isinstance(row, dict):
            continue
        sid = str(key).strip()
        telemetry = str(row.get("telemetry") or row.get("upstream_telemetry") or "").strip()
        item_events = str(row.get("item_events") or row.get("upstream_item_events") or "").strip()
        session_events = str(row.get("session_events") or row.get("upstream_session_events") or "").strip()
        if not telemetry:
            continue
        if not item_events and "/api/ingest/telemetry" in telemetry:
            item_events = telemetry.replace("/api/ingest/telemetry", "/api/ingest/item-events")
        if not session_events and "/api/ingest/telemetry" in telemetry:
            session_events = telemetry.replace("/api/ingest/telemetry", "/api/ingest/session-events")
        cleaned[sid] = {
            "telemetry": telemetry,
            "item_events": item_events,
            "session_events": session_events,
            "events": str(row.get("events") or "").strip(),
            "game_port": int(row.get("game_port") or 0),
            "server_id": sid,
            "server_name": str(row.get("server_name") or "").strip(),
        }
    try:
        timeout_sec = float(data.get("timeout_sec") or 2.0)
    except (TypeError, ValueError):
        timeout_sec = 2.0
    timeout_sec = max(0.5, min(timeout_sec, 10.0))
    with _config_lock:
        _config = {
            "enabled": bool(data.get("enabled")),
            "token": str(data.get("token") or "").strip(),
            "routes": cleaned,
            "timeout_sec": timeout_sec,
        }


def _health_payload() -> dict[str, Any]:
    with _config_lock:
        cfg = dict(_config)
    with _stats_lock:
        st = dict(_stats)
    return {
        "ok": True,
        "service": "ql-telemetry-relay",
        "enabled": cfg.get("enabled"),
        "routes": len(cfg.get("routes") or {}),
        "config_path": CONFIG_PATH,
        "version": _VERSION,
        "stats": st,
    }


def _route_for_payload(payload: dict[str, Any]) -> dict[str, str] | None:
    with _config_lock:
        if not _config.get("enabled"):
            return None
        routes = _config.get("routes") or {}
        if not routes:
            return None
        server_id = payload.get("server_id")
        if server_id is None:
            return None
        key = str(server_id).strip()
        if not key or key == "0":
            return None
        return routes.get(key)


def _enrich_forward_body(raw: bytes, payload: dict[str, Any], route: dict[str, str]) -> bytes:
    """Attach hub server_id and display name for stats-hub stream consumers."""
    try:
        data: dict[str, Any]
        if raw:
            parsed = json.loads(raw.decode("utf-8"))
            data = parsed if isinstance(parsed, dict) else dict(payload)
        else:
            data = dict(payload)
    except (UnicodeError, json.JSONDecodeError):
        return raw

    route_name = str(route.get("server_name") or "").strip()
    if route_name and not str(data.get("server_name") or "").strip():
        data["server_name"] = route_name

    route_sid = str(route.get("server_id") or "").strip()
    if route_sid.isdigit() and int(route_sid) > 0:
        sid = int(route_sid)
        data["server_id"] = sid
        data["match_id"] = f"server-{sid}"

    return json.dumps(data, ensure_ascii=False).encode("utf-8")


class RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _send_json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            self._send_json(HTTPStatus.OK, _health_payload())
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path not in (
            "/api/ingest/telemetry",
            "/api/ingest/item-events",
            "/api/ingest/session-events",
        ):
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return

        raw = self._read_body()
        payload: dict[str, Any] = {}
        if raw:
            try:
                parsed = json.loads(raw.decode("utf-8"))
                if isinstance(parsed, dict):
                    payload = parsed
            except (UnicodeError, json.JSONDecodeError):
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
                return

        route = _route_for_payload(payload)
        if route is None:
            with _stats_lock:
                _stats["dropped_no_route"] = int(_stats.get("dropped_no_route") or 0) + 1
            self._send_json(
                HTTPStatus.ACCEPTED,
                {"ok": True, "ignored": "no_route", "server_id": payload.get("server_id")},
            )
            return

        with _config_lock:
            token = str(_config.get("token") or "").strip()
            timeout = float(_config.get("timeout_sec") or 2.0)
        if not token:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": "token_missing"})
            return

        forward_body = _enrich_forward_body(raw, payload, route)

        if path.endswith("/item-events"):
            events = payload.get("events")
            event_count = len(events) if isinstance(events, list) else 1
            with _stats_lock:
                _stats["item_events_received"] = int(_stats.get("item_events_received") or 0) + event_count
            upstream = route.get("item_events") or ""
            if not upstream:
                with _stats_lock:
                    _stats["dropped_no_route"] = int(_stats.get("dropped_no_route") or 0) + 1
                self._send_json(
                    HTTPStatus.ACCEPTED,
                    {"ok": True, "ignored": "no_upstream", "server_id": payload.get("server_id")},
                )
                return
            forwarder = _items_forwarder_get()
            try:
                forwarder.forward_now(
                    url=upstream,
                    token=token,
                    body=forward_body,
                    timeout=timeout,
                    counter_key="item_events_forwarded",
                    event_count=event_count,
                )
            except (http.client.HTTPException, OSError, RuntimeError, ValueError) as exc:
                with _stats_lock:
                    _stats["forward_errors"] = int(_stats.get("forward_errors") or 0) + 1
                    _stats["last_error"] = str(exc)[:200]
                self._send_json(
                    HTTPStatus.BAD_GATEWAY,
                    {
                        "ok": False,
                        "forwarded": False,
                        "error": str(exc)[:200],
                        "server_id": payload.get("server_id"),
                    },
                )
                return
            self._send_json(
                HTTPStatus.ACCEPTED,
                {
                    "ok": True,
                    "forwarded": True,
                    "queued": True,
                    "status": "forwarded",
                    "server_id": payload.get("server_id"),
                },
            )
            return

        if path.endswith("/session-events"):
            events = payload.get("events")
            event_count = len(events) if isinstance(events, list) else 1
            with _stats_lock:
                _stats["session_events_received"] = int(_stats.get("session_events_received") or 0) + event_count
            upstream = route.get("session_events") or ""
            if not upstream:
                with _stats_lock:
                    _stats["dropped_no_route"] = int(_stats.get("dropped_no_route") or 0) + 1
                self._send_json(
                    HTTPStatus.ACCEPTED,
                    {"ok": True, "ignored": "no_upstream", "server_id": payload.get("server_id")},
                )
                return
            forwarder = _session_forwarder_get()
            try:
                forwarder.forward_now(
                    url=upstream,
                    token=token,
                    body=forward_body,
                    timeout=timeout,
                    counter_key="session_events_forwarded",
                    event_count=event_count,
                )
            except (http.client.HTTPException, OSError, RuntimeError, ValueError) as exc:
                with _stats_lock:
                    _stats["forward_errors"] = int(_stats.get("forward_errors") or 0) + 1
                    _stats["last_error"] = str(exc)[:200]
                self._send_json(
                    HTTPStatus.BAD_GATEWAY,
                    {
                        "ok": False,
                        "forwarded": False,
                        "error": str(exc)[:200],
                        "server_id": payload.get("server_id"),
                    },
                )
                return
            self._send_json(
                HTTPStatus.ACCEPTED,
                {
                    "ok": True,
                    "forwarded": True,
                    "queued": True,
                    "status": "forwarded",
                    "server_id": payload.get("server_id"),
                },
            )
            return

        with _stats_lock:
            _stats["telemetry_received"] = int(_stats.get("telemetry_received") or 0) + 1
        upstream = route.get("telemetry") or ""
        counter_key = "telemetry_forwarded"
        forwarder = _telemetry_forwarder_get()

        if not upstream:
            with _stats_lock:
                _stats["dropped_no_route"] = int(_stats.get("dropped_no_route") or 0) + 1
            self._send_json(
                HTTPStatus.ACCEPTED,
                {"ok": True, "ignored": "no_upstream", "server_id": payload.get("server_id")},
            )
            return

        status = forwarder.enqueue(
            url=upstream,
            token=token,
            body=forward_body,
            timeout=timeout,
            counter_key=counter_key,
        )
        self._send_json(
            HTTPStatus.ACCEPTED,
            {"ok": True, "queued": True, "status": status, "server_id": payload.get("server_id")},
        )


def _on_sighup(signum: int, frame: object | None) -> None:
    load_config()


def main() -> int:
    load_config()
    signal.signal(signal.SIGHUP, _on_sighup)
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), RelayHandler)
    print(
        f"ql-telemetry-relay listening on http://{LISTEN_HOST}:{LISTEN_PORT} config={CONFIG_PATH}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
