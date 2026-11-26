"""Opt-in, loopback-only read-only HTTP monitor for one GLM run.

Separate spawned process; no model calls, file reads, raw log or cancellation
authority. Local operators may use SSH forwarding. Remote bind/auth is not
implemented in this initial slice.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import multiprocessing as mp
import os
from queue import Empty, Full
import warnings

from czjLLM.job_manager.monitoring_core import MonitorEvents, MonitorProjection, MAX_COUNT

_MAX_EVENTS = 256
_HTML = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GLM 本機監控</title></head><body><h1>GLM 本機監控</h1>
<p id="health">等待監控資料</p><dl>
<dt>總列數（觀測）</dt><dd id="total">—</dd>
<dt>已排程事件累計</dt><dd id="scheduled">—</dd>
<dt>完成事件累計（非獨立寫回驗證）</dt><dd id="completed">—</dd>
<dt>監控耗時（秒）</dt><dd id="elapsed_s">—</dd></dl>
<p>僅本次 Run；不代表 GPU 使用率或 SQL/ES 獨立驗證。</p>
<script src="/app.js" defer></script></body></html>""".encode("utf-8")
_JS = """'use strict';
async function refresh() {
  const health = document.getElementById('health');
  try {
    const response = await fetch('/api/v1/status', {cache:'no-store'});
    if (!response.ok) throw Error('unavailable');
    const data = await response.json();
    health.textContent = data.delivery_incomplete || data.rejected_events ?
      '監控事件不完整；計數不可當作完整結果' : '已取得監控快照';
    for (const key of ['total','scheduled','completed','elapsed_s']) {
      const value = data[key];
      document.getElementById(key).textContent =
        value === null ? '—' : String(Math.floor(value));
    }
  } catch (_) {
    health.textContent = '監控連線中斷；以下資料非即時';
  } finally { setTimeout(refresh, 2000); }
}
refresh();""".encode("utf-8")


class _LocalHTTPServer(HTTPServer):
    allow_reuse_address = False
    timeout = 0.2

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(1.0)
        return sock, address


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        # Do not log untrusted URL/header strings to GLM.
        pass

    def _send(self, code, content_type, content):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; connect-src 'self'; "
                         "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        port = self.server.server_port
        if (self.headers.get_all("Host") not in
                ([f"127.0.0.1:{port}"], [f"localhost:{port}"])
                or self.headers.get("Sec-Fetch-Site") == "cross-site"
                or self.headers.get("Origin") not in
                (None, f"http://127.0.0.1:{port}", f"http://localhost:{port}")):
            self._send(403, "text/plain", b"Forbidden")
        elif self.path == "/":
            self._send(200, "text/html; charset=utf-8", _HTML)
        elif self.path == "/app.js":
            self._send(200, "application/javascript; charset=utf-8", _JS)
        elif self.path == "/api/v1/status":
            snapshot = self.server.projection.snapshot()
            snapshot["delivery_incomplete"] = self.server.dropped.is_set()
            self._send(200, "application/json",
                       json.dumps(snapshot, allow_nan=False).encode("utf-8"))
        else:
            self._send(404, "text/plain", b"Not found")

    def do_POST(self):
        self._send(405, "text/plain", b"Read only")


def _serve(port, total, events, dropped, stop, ready):
    try:
        server = _LocalHTTPServer(("127.0.0.1", port), _Handler)
    except OSError:
        ready.send(None)
        ready.close()
        return
    try:
        server.projection = MonitorProjection(total)
        server.dropped = dropped
        ready.send(server.server_port)
    finally:
        ready.close()
    try:
        while not stop.is_set():
            for _ in range(_MAX_EVENTS):
                try:
                    kind, payload = events.get_nowait()
                except Empty:
                    break
                server.projection.apply(kind, payload)
            server.handle_request()
    finally:
        server.server_close()


class WebMonitorClient:
    """Parent-side nonblocking numeric-event adapter; no private payload IPC."""

    def __init__(self, process, events, dropped, stop, port):
        self._process, self._events = process, events
        self._dropped, self._stop = dropped, stop
        self.port = port
        self._closed = False

    def _emit(self, kind, value):
        if self._closed:
            return
        if type(value) is not int or not 0 <= value <= MAX_COUNT:
            self._dropped.set()
            return
        try:
            self._events.put_nowait((kind, value))
        except (Full, OSError, ValueError):
            self._dropped.set()

    def inc_sched(self, n=1): self._emit(MonitorEvents.INC_SCHED, n)
    def inc_done(self, n=1): self._emit(MonitorEvents.INC_DONE, n)
    def set_total(self, total): self._emit(MonitorEvents.SET_TOTAL, total)
    # Interface-compatible private/unsupported events: never send them.
    def log(self, text): pass
    def set_audit_path(self, path): pass
    def set_quality_event_path(self, path): pass
    def set_recovery_meter_path(self, path): pass
    def update_recheck_stats(self, stats): pass
    def update_reduction_stats(self, stats, final=False): pass
    def cancellation_requested(self): return False

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        try:
            self._process.join(2)
            if self._process.is_alive():
                # This is only the disposable monitor process, never a Worker.
                self._process.terminate()
                self._process.join(1)
        finally:
            self._events.cancel_join_thread()
            self._events.close()


def start_web_monitor(total, port):
    """Start a disposable service; return None on port/startup failure."""
    MonitorProjection(total)  # validate before spawning
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("invalid monitor port")
    ctx = mp.get_context("spawn")
    events = ctx.Queue(maxsize=_MAX_EVENTS)
    events.cancel_join_thread()
    dropped, stop = ctx.Event(), ctx.Event()
    recv, send = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_serve, args=(port, total, events, dropped, stop, send),
                          daemon=True, name="glm-web-monitor")
    client = None
    started = False
    try:
        process.start()
        started = True
        send.close()
        if recv.poll(5):
            actual = recv.recv()
            if type(actual) is int and 0 < actual <= 65535:
                client = WebMonitorClient(process, events, dropped, stop, actual)
    except (OSError, EOFError, RuntimeError):
        pass
    finally:
        recv.close()
        send.close()
        if client is None:
            stop.set()
            if started:
                process.join(1)
                if process.is_alive():
                    process.terminate()
                    process.join(1)
            events.close()
    return client


def try_start_web_monitor(total, environ=None):
    env = os.environ if environ is None else environ
    try:
        if env.get("GLM_WEB_HOST", "127.0.0.1") != "127.0.0.1":
            raise ValueError("only loopback is supported")
        port = int(env.get("GLM_WEB_PORT", "9010"))
        if not 1 <= port <= 65535:
            raise ValueError("invalid port")
        client = start_web_monitor(total, port)
        if client is not None:
            return client
    except Exception:
        pass
    warnings.warn("GLM Web monitor unavailable; processing continues without it",
                  RuntimeWarning)
    return None
