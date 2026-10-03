"""Output freshness and rerun policy shared by Elasticsearch adapters."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from czjLLM.common.pending_conditions import clean_output_cols
from czjLLM.common.pending_decision import PendingDecision
from czjLLM.es_mode.model_metadata import safe_model_tag
from .value_helpers import (
    deep_collect_by_path as _deep_collect_by_path,
    extract_by_path as _extract_by_path,
    flatten_list as _flatten_list,
    is_non_empty_deep as _is_non_empty_deep,
    is_valid_date_string as _is_valid_date_string,
    normalize_scalar as _norm_scalar,
)


class ElasticsearchPendingPolicyMixin:
    """Encapsulate output completeness, freshness, and rerun decisions."""

    def _resolve_meta_field(self, output_col: str) -> Optional[str]:
        rr = (self.cfg or {}).get("rerun") or {}
        mf = rr.get("meta_field")
        return mf or (f"{output_col}_meta" if output_col else None)

    def _resolve_output_cols(self, output_col: Any = None, output_cols: Any = None) -> List[str]:
        raw = output_cols
        if raw is None:
            raw = self.cfg.get("output_cols")
        if raw is None:
            raw = output_col
        if raw is None:
            raw = self.cfg.get("output_col")
        if isinstance(raw, (list, tuple)):
            return clean_output_cols(list(raw))
        return clean_output_cols([raw])

    def _output_meta_fields(self, output_cols: List[str]) -> List[str]:
        fields = []
        for col in output_cols:
            mf = self._resolve_meta_field(col)
            if mf:
                fields.append(mf)
        return list(dict.fromkeys(fields))

    def _is_fresh_outputs_all(self, src: dict, output_cols: List[str]) -> bool:
        cols = self._resolve_output_cols(output_cols=output_cols)
        if not cols:
            return False
        return all(self._is_fresh_output(src, col) for col in cols)

    def _output_stale_reasons(self, src: dict, output_col: str) -> list[str]:
        if not _is_non_empty_deep(_extract_by_path(src, output_col)):
            return ["missing_output"]
        if not self._validate_required_output_checks(src, output_col):
            return ["required_output_invalid"]
        rr = (self.cfg or {}).get("rerun") or {}
        expected = rr.get("execution_fingerprint")
        tag = safe_model_tag(rr.get("model_tag"))
        pipeline_hash = rr.get("pipeline_hash")
        if not rr.get("enable") and not expected:
            return []
        meta_field = self._resolve_meta_field(output_col)
        meta = _extract_by_path(src, meta_field) if meta_field else None
        reasons = []
        if expected:
            persisted = _extract_by_path(meta, "execution_fingerprint") if meta else None
            reasons.append("missing_processing_identity" if not persisted else
                           "execution_fingerprint_mismatch" if persisted != expected else "")
        if tag:
            persisted_tag = _extract_by_path(meta, "model_tag") if meta else None
            reasons.append("missing_meta" if not persisted_tag else
                           "model_tag_mismatch" if persisted_tag != tag else "")
        if pipeline_hash:
            persisted_pipeline = _extract_by_path(meta, "pipeline_hash") if meta else None
            reasons.append("missing_meta" if not persisted_pipeline else
                           "pipeline_hash_mismatch" if persisted_pipeline != pipeline_hash else "")
        if rr.get("force_if_missing_meta") and meta_field and meta is None:
            reasons.append("missing_meta")

        processed_at = _extract_by_path(meta, "processed_at") if meta else None
        if processed_at is None:
            processed_at = _extract_by_path(src, "update_time_ai")
        try:
            processed_dt = datetime.fromisoformat(str(processed_at).replace("Z", "+00:00"))
        except Exception:
            processed_dt = None
        stale_days = rr.get("stale_after_days")
        if stale_days and processed_dt is not None:
            try:
                if processed_dt < datetime.now(timezone.utc) - timedelta(days=int(stale_days)):
                    reasons.append("stale_after_days")
            except (TypeError, ValueError):
                pass
        since = rr.get("force_since")
        if since and processed_dt is not None:
            try:
                since_dt = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
                if processed_dt < since_dt:
                    reasons.append("force_since")
            except Exception:
                pass
        return list(dict.fromkeys(reason for reason in reasons if reason))

    def check_source_pending(self, src: dict, output_cols: List[str]) -> PendingDecision:
        """Explain the exact cumulative policy used by discovery and recheck."""
        cols = self._resolve_output_cols(output_cols=output_cols)
        reasons = []
        for col in cols:
            reasons.extend(self._output_stale_reasons(src, col))
        reasons = list(dict.fromkeys(reasons or (["missing_output"] if not cols else [])))
        if not reasons:
            return PendingDecision(False, "fresh_completed")
        primary = reasons[0]
        diagnostics = {}
        expected = ((self.cfg or {}).get("rerun") or {}).get("execution_fingerprint")
        if primary in {"missing_processing_identity", "execution_fingerprint_mismatch"}:
            diagnostics["expected_execution_fingerprint"] = expected
            for col in cols:
                meta = _extract_by_path(src, self._resolve_meta_field(col))
                persisted = _extract_by_path(meta, "execution_fingerprint") if meta else None
                matches_primary = (
                    (primary == "missing_processing_identity" and not persisted) or
                    (primary == "execution_fingerprint_mismatch" and persisted and persisted != expected)
                )
                if matches_primary:
                    if persisted:
                        diagnostics["persisted_execution_fingerprint"] = persisted
                    break
        if len(reasons) > 1:
            diagnostics["secondary_reasons"] = reasons[1:8]
        return PendingDecision(True, primary, diagnostics)

    def _is_pending_by_outputs(self, src: dict, output_cols: List[str]) -> bool:
        return self.check_source_pending(src, output_cols).pending

    def _bulk_check_present_nonempty(
        self, *, tgt_index: str, pk: str, ids: List[str],
        output_col: Any = None, output_cols: Any = None, request_timeout: int,
    ) -> set:
        assert self.es is not None
        present = set()
        output_cols_resolved = self._resolve_output_cols(output_col=output_col, output_cols=output_cols)
        if not output_cols_resolved:
            return present
        if not ids:
            return present

        # ✅ 先把查詢用的 ids 統一標準化，過濾掉 None
        ids_norm = []
        for v in ids:
            nv = _norm_scalar(v)
            if nv is not None:
                ids_norm.append(nv)
        if not ids_norm:
            return present

        if pk == "_id":
            # 直接用 mget
            docs = self.es.mget(index=tgt_index, body={"ids": ids_norm},
                                request_timeout=request_timeout)
            for d in docs.get("docs", []):
                if not d.get("found"):
                    continue
                src = d.get("_source", {}) or {}
                #val = _extract_by_path(src, output_col)
                #if _is_non_empty_deep(val):
                if self._is_fresh_outputs_all(src, output_cols_resolved):
                    # ✅ 放入 present 前也標準化，避免 _id 型態不一
                    present.add(_norm_scalar(d.get("_id")))
            return present

        # pk 不是 _id：用 search terms 查詢
        pk_keyword = pk + self.cfg.get("pk_keyword_suffix", ".keyword")
        try:
            m = self.get_field_mapping(tgt_index, pk)
            has_keyword = isinstance(m, dict) and "fields" in m and "keyword" in m["fields"]
        except Exception:
            has_keyword = False

        term_field = pk_keyword if has_keyword else pk

        rr = (self.cfg or {}).get("rerun") or {}
        fallback_date = rr.get("fallback_date_field") or self.cfg.get("fallback_date_field") or "update_time_ai"

        src_fields = [pk] + output_cols_resolved + self._output_meta_fields(output_cols_resolved)
        if fallback_date:
            src_fields.append(fallback_date)
        # 去重
        src_fields = list(dict.fromkeys(src_fields))

        batch = 1000
        for i in range(0, len(ids_norm), batch):
            chunk = ids_norm[i:i+batch]          # ✅ 已是標準化後的字串
            q = {
                "query": {"terms": {term_field: chunk}},
                #"_source": [pk, output_col],
                "_source": src_fields,
                "size": len(chunk)
            }
            res = self.es.search(index=tgt_index, body=q, request_timeout=request_timeout)
            for hit in res.get("hits", {}).get("hits", []):
                src = hit.get("_source", {}) or {}
                #val = _extract_by_path(src, output_col)
                #if _is_non_empty_deep(val):
                #    key_val = _extract_by_path(src, pk)
                if self._is_fresh_outputs_all(src, output_cols_resolved):
                    key_val = _extract_by_path(src, pk)
                    key_val = _norm_scalar(key_val)     # ✅ 放入前標準化
                    if key_val is not None:
                        present.add(key_val)
        return present


    def _needs_rerun_clause(self, index: str, output_col: str) -> Optional[dict]:
        rr = (self.cfg or {}).get("rerun") or {}
        if not rr.get("enable") and not rr.get("execution_fingerprint"):
            return None
        #print("rr in _needs_rerun_clause",rr)
        #print("-"*50)
        #meta      = rr.get("meta_field") or f"{output_col}_meta"  # e.g. "multidim_event_json_meta"
        meta      = self._resolve_meta_field(output_col)  # ← 統一來源
        #print("meta",meta)
        tag       = safe_model_tag(rr.get("model_tag"))
        pipe      = rr.get("pipeline_hash")
        execution_fingerprint = rr.get("execution_fingerprint")
        since     = rr.get("force_since")
        stale_days= rr.get("stale_after_days")
        force_if_missing_meta = rr.get("force_if_missing_meta", False)

        # 這行改成同時支援 rerun 與全域（你檔案就是放全域）
        #print("self.cfg in needs_rerun",self.cfg)
        fallback_date = (
            rr.get("fallback_date_field")
            or self.cfg.get("fallback_date_field")
            or "update_time_ai"
        )


        should = []

        # A) 版本/管線比對（有 meta 才比）
        if tag and meta:
            should.append({"bool":{"must":[{"exists":{"field":output_col}}],
                                   "must_not":[{"term":{f"{meta}.model_tag.keyword":tag}}]}})
        if pipe and meta:
            should.append({"bool":{"must":[{"exists":{"field":output_col}}],
                                   "must_not":[{"term":{f"{meta}.pipeline_hash.keyword":pipe}}]}})
        if execution_fingerprint and meta:
            should.append({"bool":{"must":[{"exists":{"field":output_col}}],
                                   "must_not":[{"term":{f"{meta}.execution_fingerprint.keyword":execution_fingerprint}}]}})

        # B) 逾期（stale_days）
        if stale_days:
            if meta:
                should.append({"range": {f"{meta}.processed_at": {"lt": f"now-{int(stale_days)}d"}}})
            if fallback_date:
                # 若 fallback_date 是 date mapping，這條會生效
                should.append({"range": {fallback_date: {"lt": f"now-{int(stale_days)}d"}}})

        # C) 強制時間窗（since）
        if since:
            if meta:
                should.append({"range": {f"{meta}.processed_at": {"lt": since}}})
            if fallback_date:
                # 1) date-mapped 的正常 range
                should.append({"range": {fallback_date: {"lt": since}}})
                # 2) 非 date-mapped 的字串比較備援（有 output 才需要重跑）
                should.append({
                    "bool": {
                        "must": [
                            {"exists": {"field": output_col}},
                            {"script": {
                                "script": {
                                    "lang": "painless",
                                    "source": """
                                        def v = params._source.get(params.fd);
                                        if (v == null) return false;
                                        def s = v instanceof List ? (v.size() > 0 ? v.get(0) : null) : v;
                                        if (s == null) return false;
                                        return s.compareTo(params.since) < 0;
                                    """,
                                    "params": {"fd": fallback_date, "since": since}
                                }
                            }}
                        ]
                    }
                })

        # D) 有 output 但缺 meta → 也當需重跑
        #print("force_if_missing_meta",force_if_missing_meta)
        #print("meta",meta)
        if force_if_missing_meta and meta:
            #print("GOGOGO")
            should.append({
                "bool": {
                    "must":     [{"exists": {"field": output_col}}],
                    "must_not": [{"exists": {"field": meta}}]
                }
            })

        if not should:
            return None
        return {"bool": {"should": should, "minimum_should_match": 1}}

    def _get_required_output_checks(self, output_col: str) -> List[Dict[str, Any]]:
        """
        從 cfg/rerun 讀取必要輸出欄位檢查設定。
        支援：
          - 字串寫法: "Event_Timeline.date_iso"
          - dict 寫法: {"path": "...", "validator": "date", ...}
        預設 path 視為相對於 output_col。
        """
        rr = (self.cfg or {}).get("rerun") or {}
        raw_checks = rr.get("required_output_checks") or self.cfg.get("required_output_checks") or []
        if not raw_checks:
            return []

        out = []
        for item in raw_checks:
            if isinstance(item, str):
                item = {"path": item}

            if not isinstance(item, dict):
                continue

            path = (item.get("path") or "").strip()
            if not path:
                continue

            relative = item.get("relative_to_output", True)

            # 支援 absolute path；若不是 absolute，就自動補 output_col 前綴
            if relative and output_col and not (path == output_col or path.startswith(output_col + ".")):
                full_path = f"{output_col}.{path}"
            else:
                full_path = path

            cfg_item = dict(item)
            cfg_item["full_path"] = full_path
            out.append(cfg_item)

        return out

    def _validate_required_output_checks(self, src: dict, output_col: str) -> bool:
        """
        檢查 output_col 內是否滿足必要 key 條件。
        規則預設：每個 check 至少找到 1 個合法值（min_valid_count=1）。
        """
        rr = (self.cfg or {}).get("rerun") or {}
        if not rr.get("enable") and not (self.cfg or {}).get("required_output_checks_apply_without_rerun", False):
            return True

        checks = self._get_required_output_checks(output_col)
        if not checks:
            return True

        for ck in checks:
            full_path = ck["full_path"]
            validator = (ck.get("validator") or "non_empty").lower()
            fmt = ck.get("format")
            min_valid_count = int(ck.get("min_valid_count", 1))

            raw_vals = _deep_collect_by_path(src, full_path)
            vals = _flatten_list(raw_vals)

            valid_count = 0
            for v in vals:
                if validator == "date":
                    if _is_valid_date_string(v, fmt or "yyyy-MM-dd"):
                        valid_count += 1
                else:
                    # 預設 non_empty
                    if _is_non_empty_deep(v):
                        valid_count += 1

                if valid_count >= min_valid_count:
                    break

            if valid_count < min_valid_count:
                # debug 可選
                print(f"[DEBUG] required_output_check failed: path={full_path}, "
                      f"validator={validator}, format={fmt}, found_valid={valid_count}, "
                      f"min_valid_count={min_valid_count}")
                return False

        return True

    def _is_fresh_output(self, src: dict, output_col: str) -> bool:
        return not self._output_stale_reasons(src, output_col)
