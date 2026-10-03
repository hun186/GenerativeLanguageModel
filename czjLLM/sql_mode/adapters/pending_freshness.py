"""One SQL freshness contract shared by discovery and dispatch recheck."""

from __future__ import annotations

from typing import Callable

from czjLLM.common.pending_conditions import build_any_output_missing_condition


def semantic_freshness_config(cfg: dict) -> tuple[str | None, str | None]:
    semantic = (cfg or {}).get("semantic_freshness") or {}
    expected = semantic.get("execution_fingerprint") or (cfg or {}).get("expected_execution_fingerprint")
    column = semantic.get("processing_identity_column") or (cfg or {}).get("processing_identity_column")
    if not expected:
        return None, None
    if not column:
        raise ValueError("processing_identity_column is required when execution_fingerprint freshness is enabled")
    return str(expected), str(column)


def build_pending_condition(output_cols, quote: Callable[[str], str], trim_expr, *, cfg: dict, prefix="tgt."):
    missing = build_any_output_missing_condition(output_cols, quote, trim_expr, prefix=prefix)
    expected, column = semantic_freshness_config(cfg)
    if expected is None:
        return missing, []
    expr = f"{prefix}{quote(column)}"
    return f"({missing}) OR ({expr} IS NULL OR {trim_expr(expr)} = '' OR {expr} <> ?)", [expected]


def validate_processing_identity_column(ctx) -> None:
    """Reject an explicit metadata column that could overwrite business data."""
    identity = str(getattr(ctx, "processing_identity_column", "") or "").strip()
    if not getattr(ctx, "expected_execution_fingerprint", None) or not identity:
        return
    protected = [getattr(ctx, "primary_key", ""), getattr(ctx, "input_col", "")]
    protected.extend(getattr(ctx, "output_cols", None) or [getattr(ctx, "output_col", "")])
    protected.extend(rule.get("output_col", "") for rule in (getattr(ctx, "sql_writeback_rules", None) or []) if isinstance(rule, dict))
    if bool(getattr(ctx, "sql_expand_json_to_columns", False)):
        prefix = str(getattr(ctx, "sql_expand_json_prefix", "") or "").strip()
        for value in (getattr(ctx, "allowed_output_fields", None) or []):
            name = str(value).strip()
            if name:
                protected.append(f"{prefix}{name}" if prefix else name)
    normalized = {str(value).strip().casefold() for value in protected if str(value).strip()}
    if identity.casefold() in normalized:
        raise ValueError(f"processing_identity_column {identity!r} conflicts with a primary/input/output destination column")
