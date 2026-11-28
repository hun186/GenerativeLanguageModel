"""Opt-in, loopback-only read-only HTTP monitor for one GLM run.

Separate spawned process; no model calls, arbitrary file reads, raw log or cancellation
authority. Local operators may use SSH forwarding. Remote bind/auth is not
implemented in this initial slice.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import multiprocessing as mp
import os
import threading
from queue import Empty, Full
import warnings

from czjLLM.job_manager.monitoring_core import MonitorEvents, MonitorProjection, MAX_COUNT
from czjLLM.job_manager.web_document_monitor import DocumentMonitor
from czjLLM.job_manager.web_quality_monitor import WebQualityMonitor

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
<h2>目前處理文件（匿名識別碼）</h2><p id="doc-status">等待 Run Meter</p>
<table><thead><tr><th>文件</th><th>階段</th><th>切片</th><th>等待</th><th>執行</th></tr></thead>
<tbody id="doc-rows"></tbody></table>
<p>僅第一頁，切片完成不等於寫回完成。</p>
<h2>Worker 呼叫活動（目前頁，匿名端點）</h2>
<p id="worker-status">等待觀測</p>
<table><thead><tr><th>文件</th><th>端點</th><th>最後狀態</th><th>計時</th><th>資料觀測</th></tr></thead>
<tbody id="worker-rows"></tbody></table>
<p>非全 Run 統計；GPU 使用率未知。</p>
<h2>Audit 效能統計（目前 Run）</h2><p id="audit-status">等待 Audit</p>
<p id="audit-cache"></p>
<table><thead><tr><th>指標</th><th>樣本數</th><th>P50</th><th>P95</th><th>Max</th></tr></thead>
<tbody id="audit-rows"></tbody></table>
<h3>串流時間（用戶端量測；所有 Audit 呼叫）</h3>
<p id="stream-coverage"></p>
<table><thead><tr><th>指標</th><th>樣本數</th><th>P50</th><th>P95</th><th>Max</th></tr></thead>
<tbody id="stream-rows"></tbody></table>
<p>TTFT 是首段非空思考或回答文字，不等於 Prefill；原生 Prefill／Decode 未知。</p>
<h3>模型／Context／端點比較（匿名）</h3>
<p id="comparison-coverage"></p>
<table><thead><tr><th>Model</th><th>Endpoint</th><th>Context / source</th><th>Calls</th><th>Failure %</th><th>TTFT P50/P95 (n)</th><th>Slice P50/P95 (n)</th><th>Total tok/s P50 (n)</th><th>Cache % (reported/eligible)</th></tr></thead>
<tbody id="comparison-rows"></tbody></table>
<p>依原始 Audit 的模型、端點、Context 上限及來源分組。未識別與超額組別另計；不代表 GPU 利用率或已設定的 num_ctx。</p>
<h2>品質與異常事件（本次 Run）</h2>
<p id="quality-status">等待品質事件</p>
<table><thead><tr><th>品質指標</th><th>觀測值</th></tr></thead><tbody id="quality-rows"></tbody></table>
<h3>執行異常（事件數，非失敗文件數）</h3>
<table><thead><tr><th>異常類別</th><th>次數</th></tr></thead><tbody id="quality-incidents"></tbody></table>
<p>JSON 修復成功不代表語意正確；Sink 確認不等於獨立讀回驗證。原始 JSON 不提供。</p>
<script src="/app.js" defer></script></body></html>""".encode("utf-8")
_JS = """'use strict';
function showDocuments(doc) {
  const tbody = document.getElementById('doc-rows');
  tbody.replaceChildren();
  const status = document.getElementById('doc-status');
  if (doc.status !== 'observed') {
    const labels = {waiting_for_meter:'等待 Run Meter', unavailable:'文件快照暫不可讀',
      stale:'文件快照逾時', delivery_incomplete:'監控交接不完整'};
    status.textContent = labels[doc.status] || '文件觀測不可用';
    return;
  }
  status.textContent = '目前處理 ' + doc.matching + ' 列；顯示 ' + doc.rows.length +
    ' 列；未顯示 ' + doc.omitted + ' 列；異常 ' + doc.errors + ' 列';
  for (const row of doc.rows) {
    const tr = document.createElement('tr');
    for (const value of [row.alias, row.stage,
      (row.done ?? '—') + '/' + (row.total ?? '—'), row.pending, row.running]) {
      const td = document.createElement('td');
      td.textContent = value ?? '—';
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}
function showWorkers(doc) {
  const tbody = document.getElementById('worker-rows');
  tbody.replaceChildren();
  const status = document.getElementById('worker-status');
  const workers = doc.status === 'observed' ? doc.workers : null;
  if (!workers || workers.status !== 'observed') {
    status.textContent = workers?.status === 'waiting_for_audit' ?
      '尚未收到 Audit 路徑' : 'Worker 觀測暫不可用';
    return;
  }
  status.textContent = '最後觀測 ' + workers.count + ' 個呼叫；顯示 ' +
    workers.calls.length + ' 個；省略 ' + workers.omitted + ' 個；' +
    workers.running_rows_without_observations + ' 個執行中文件無活動觀測';
  const phases = {started:'等待首段資料', received:'已收到資料',
    assembled:'串流已組裝', failed:'串流失敗'};
  for (const call of workers.calls) {
    const tr = document.createElement('tr');
    const stage = (call.status === 'assigned' ? '已分派' : '呼叫中') +
      (call.stream_event ? '／' + phases[call.stream_event] : '');
    const detail = call.chunks === null ? '未提供串流觀測' :
      call.chunks + ' chunks；思考' + (call.thinking_seen ? '有' : '未觀測') +
      '；回答' + (call.content_seen ? '有' : '未觀測');
    for (const value of [call.row_alias, call.endpoint_alias ?? '未知',
      stage, call.clock_text, detail]) {
      const td = document.createElement('td');
      td.textContent = value;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}
function showAudit(audit) {
  const tbody = document.getElementById('audit-rows');
  tbody.replaceChildren();
  const status = document.getElementById('audit-status');
  const cache = document.getElementById('audit-cache');
  cache.textContent = '';
  const coverage = document.getElementById('stream-coverage');
  const streamBody = document.getElementById('stream-rows');
  coverage.textContent = '';
  streamBody.replaceChildren();
  const compBody = document.getElementById('comparison-rows');
  const compCoverage = document.getElementById('comparison-coverage');
  compBody.replaceChildren();
  compCoverage.textContent = '';
  if (audit?.status !== 'observed') {
    status.textContent = audit?.status === 'catching_up' ?
      'Audit 增量讀取中：' + audit.scanned_bytes + '/' + audit.total_bytes + ' bytes；尚非完整統計' :
      'Audit 尚未取得、逾時、交接不完整或超過讀取預算';
    return;
  }
  status.textContent = '呼叫 ' + audit.calls + ' 次；失敗 ' + audit.failures +
    ' 次；分布不是時間序列';
  const c = audit.provider_cache;
  cache.textContent = 'Provider cache ' + (c.hit_pct === null ? '未知' : c.hit_pct.toFixed(1) + '%') +
    '；回報覆蓋 ' + c.observed_rows + '/' + c.eligible_rows;
  const labels = {input_tokens:'Input tokens',output_tokens:'Output tokens',
    template_tokens:'Template tokens',task_text_tokens:'Task text tokens',
    context_usage_ratio:'Context %',elapsed_seconds:'Slice time (s)',
    total_tok_per_s:'Total tok/s',effective_tok_per_s_est:'Effective tok/s (est.)'};
  for (const [key,label] of Object.entries(labels)) {
    const v = audit.metrics[key];
    const tr = document.createElement('tr');
    for (const value of [label, v.count, v.p50, v.p95, v.max]) {
      const td = document.createElement('td');
      td.textContent = value === null ? '未知' :
        typeof value === 'number' ? Number(value.toFixed(2)).toLocaleString() : value;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  const stream = audit.stream_timing;
  if (!stream) return;
  coverage.textContent = '已量測 ' + stream.observed_rows + '/' + stream.audit_rows +
    '；未回報 ' + stream.unreported_rows + '；無文字 ' + stream.no_text_rows +
    '；不合法 ' + stream.invalid_rows + '。覆蓋率不代表串流成功率。';
  const streamLabels = {stream_ttft_seconds:'TTFT (s)',
    stream_first_thinking_seconds:'First thinking (s)',
    stream_first_content_seconds:'First content (s)',stream_chunks:'Chunks'};
  for (const [key,label] of Object.entries(streamLabels)) {
    const v = stream.metrics[key];
    const tr = document.createElement('tr');
    for (const value of [label, v.count, v.p50, v.p95, v.max]) {
      const td = document.createElement('td');
      td.textContent = value === null ? '未知' :
        typeof value === 'number' ? Number(value.toFixed(3)).toLocaleString() : value;
      tr.appendChild(td);
    }
    streamBody.appendChild(tr);
  }
  const comp = audit.comparison;
  if (!comp) return;
  compCoverage.textContent = '已分組 ' + comp.grouped_rows + '/' + comp.total_rows +
    '；未識別 ' + comp.unidentified_rows + '；超額省略 ' + comp.omitted_rows +
    '；最多 ' + comp.group_limit + ' 組。';
  const fmt = v => v === null ? '未知' : Number(v.toFixed(2)).toLocaleString();
  const pair = v => fmt(v.p50) + '/' + fmt(v.p95) + ' (' + v.count + ')';
  for (const g of comp.groups) {
    const tr = document.createElement('tr');
    const c = g.provider_cache;
    for (const value of ['M-' + g.model_alias, 'E-' + g.endpoint_alias,
      (g.context_limit_tokens === null ? '未知' : g.context_limit_tokens) + ' / ' + g.context_limit_source,
      g.calls, fmt(g.failure_pct), pair(g.ttft), pair(g.slice_time),
      fmt(g.total_tok_per_s.p50) + ' (' + g.total_tok_per_s.count + ')',
      fmt(c.hit_pct) + ' (' + c.observed_rows + '/' + c.eligible_rows + ')']) {
      const td = document.createElement('td');
      td.textContent = value;
      tr.appendChild(td);
    }
    compBody.appendChild(tr);
  }
}
function showQuality(q) {
  const status = document.getElementById('quality-status');
  const rows = document.getElementById('quality-rows');
  const incidents = document.getElementById('quality-incidents');
  rows.replaceChildren();
  incidents.replaceChildren();
  if (q?.status !== 'observed') {
    const labels = {waiting_for_quality:'等待品質事件',not_initialized:'尚未取得品質事件',
      stale:'品質快照逾時', delivery_incomplete:'監控交接不完整',
      incomplete_tail:'末行寫入中，暫不提供完整統計',degraded_corrupt_lines:'品質事件損毀，請檢查離線報告',
      unsealed_legacy:'歷史封存未驗證，請檢查離線報告',
      capacity_exceeded:'超過安全累計上限，請使用離線報告',unverified:'品質事件驗證異常'};
    status.textContent = labels[q?.status] || '品質觀測不可用';
    return;
  }
  status.textContent = '已觀測 ' + q.events + ' 筆去重品質事件';
  const ratio = (n,d,p) => p === null ? '樣本不足' : n + '/' + d + ' (' + p.toFixed(2) + '%)';
  const append = (body, label, value) => {
    const tr = document.createElement('tr');
    for (const v of [label, value]) {
      const td = document.createElement('td');
      td.textContent = v;
      tr.appendChild(td);
    }
    body.appendChild(tr);
  };
  append(rows,'初次 JSON 不合法',ratio(q.slice_initial_invalid,q.slice_validation_attempts,q.slice_initial_invalid_pct));
  append(rows,'JSON 修復成功',ratio(q.repair_succeeded,q.repair_attempts,q.repair_success_pct));
  append(rows,'文件結構異常（待處理）',ratio(q.documents_schema_pending,q.documents_decided,q.document_schema_reject_pct));
  append(rows,'確認式 Sink 寫回',q.documents_writeback_confirmed);
  for (const [key,label] of Object.entries({
    consumer_orchestration_failure_events:'Consumer 調度',
    row_merger_retryable_failure_events:'Row Merger 暫時異常',
    producer_operational_failure_events:'Producer 執行',
    stage_orchestration_failure_events:'Stage 調度',
    worker_phase_failure_events:'Worker 階段'})) append(incidents,label,q[key]);
  for (const [key,value] of Object.entries(q.incident_codes)) append(incidents,key,value);
}
async function refresh() {
  const health = document.getElementById('health');
  try {
    const response = await fetch('/api/v1/status', {cache:'no-store'});
    if (!response.ok) throw Error('unavailable');
    const data = await response.json();
    health.textContent = data.delivery_incomplete || data.rejected_events ?
      '監控事件不完整；計數不可當作完整結果' : '已取得監控快照';
    showDocuments(data.documents);
    showWorkers(data.documents);
    showAudit(data.audit);
    showQuality(data.quality);
    for (const key of ['total','scheduled','completed','elapsed_s']) {
      const value = data[key];
      document.getElementById(key).textContent =
        value === null ? '—' : String(Math.floor(value));
    }
  } catch (_) {
    health.textContent = '監控連線中斷；以下資料非即時';
    showDocuments({status:'unavailable', rows:[]});
    showWorkers({status:'unavailable'});
    showAudit({status:'unavailable'});
    showQuality({status:'unavailable'});
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
            snapshot["documents"] = ({"status": "delivery_incomplete", "rows": []}
                if snapshot["delivery_incomplete"] else self.server.documents.snapshot())
            snapshot["audit"] = ({"status": "delivery_incomplete"} if snapshot["delivery_incomplete"]
                                 else self.server.documents.audit_snapshot())
            snapshot["quality"] = ({"status": "delivery_incomplete"} if snapshot["delivery_incomplete"]
                                   else self.server.quality.snapshot())
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
        server.documents = DocumentMonitor()
        reader = threading.Thread(target=server.documents.run, args=(stop,),
                                  daemon=True, name='web-meter-reader')
        reader.start()
        server.quality = WebQualityMonitor()
        quality_reader = threading.Thread(target=server.quality.run, args=(stop,),
                                          daemon=True, name='web-quality-reader')
        quality_reader.start()
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
                if kind == MonitorEvents.RECOVERY_METER:
                    server.documents.set_path(payload)
                elif kind == MonitorEvents.AUDIT_PATH:
                    server.documents.set_audit_path(payload)
                elif kind == MonitorEvents.QUALITY_PATH:
                    server.quality.set_path(payload)
                else:
                    server.projection.apply(kind, payload)
            server.handle_request()
    finally:
        server.server_close()


class WebMonitorClient:
    """Bounded event adapter; meter locator travels only in trusted internal IPC."""

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
    # Private diagnostic payloads remain excluded; only the meter locator is accepted.
    def log(self, text): pass
    def set_audit_path(self, path):
        self._set_locator(MonitorEvents.AUDIT_PATH, path)
    def set_quality_event_path(self, path):
        self._set_locator(MonitorEvents.QUALITY_PATH, path)
    def set_recovery_meter_path(self, path):
        self._set_locator(MonitorEvents.RECOVERY_METER, path)

    def _set_locator(self, event, path):
        if self._closed:
            return
        try:
            path = str(path or "")
            if len(path) > 4096 or "\x00" in path:
                raise ValueError("invalid meter path")
            self._events.put_nowait((event, path))
        except (Full, OSError, ValueError):
            self._dropped.set()
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
