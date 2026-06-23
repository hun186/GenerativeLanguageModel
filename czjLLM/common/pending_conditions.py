from typing import Callable, List


def clean_output_cols(output_cols: List[str]) -> List[str]:
    return [str(c).strip() for c in (output_cols or []) if c is not None and str(c).strip()]


def build_all_outputs_complete_condition(
    output_cols: List[str],
    quote: Callable[[str], str],
    trim_expr: Callable[[str], str],
) -> str:
    cols = clean_output_cols(output_cols)
    if not cols:
        return "1 = 0"
    return " AND ".join(
        [f"({quote(c)} IS NOT NULL AND {trim_expr(quote(c))} <> '')" for c in cols]
    )


def build_any_output_missing_condition(
    output_cols: List[str],
    quote: Callable[[str], str],
    trim_expr: Callable[[str], str],
    *,
    prefix: str = "tgt.",
) -> str:
    cols = clean_output_cols(output_cols)
    if not cols:
        return "1 = 1"
    return " OR ".join(
        [
            f"({prefix}{quote(c)} IS NULL OR {trim_expr(prefix + quote(c))} = '')"
            for c in cols
        ]
    )
