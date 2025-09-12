def build_empty_clause(quoted_cols, prefix=""):
    parts = []
    for c in quoted_cols:
        col = f"{prefix}{c}"
        # SQL Server/SQLite 皆可：去頭尾空白後比對空字串
        parts.append(f"({col} IS NULL OR LTRIM(RTRIM({col})) = '')")
    return " AND ".join(parts)