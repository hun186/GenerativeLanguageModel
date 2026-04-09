from czjLLM.sql_utils.common import quote_column

def upsert_single_value(ctx, cursor, pk, result, is_sqlite, update_time=None):
    if is_sqlite:
        # 直接用 ON CONFLICT
        cols = [ctx.primary_key, ctx.output_col]
        vals = [pk, result]
        if ctx.record_update_time:
            cols.append("update_time")
            vals.append(update_time)
        set_clause = f"{quote_column(ctx.output_col)} = excluded.{quote_column(ctx.output_col)}"
        if ctx.record_update_time:
            set_clause += f", update_time = excluded.update_time"

        insert_sql = f"""
            INSERT INTO {quote_column(ctx.target_table)} ({', '.join(quote_column(c) for c in cols)})
            VALUES ({', '.join(['?'] * len(cols))})
            ON CONFLICT({quote_column(ctx.primary_key)}) DO UPDATE SET {set_clause}
        """
        cursor.execute(insert_sql, vals)

    else:
        # SQL Server: UPDATE -> fallback INSERT
        update_expr = f"{quote_column(ctx.output_col)} = ?"
        params = [result]
        if ctx.record_update_time:
            update_expr += ", update_time = ?"
            params.append(update_time)
        update_sql = f"""
            UPDATE {quote_column(ctx.target_table)}
            SET {update_expr}
            WHERE {quote_column(ctx.primary_key)} = ?
        """
        params.append(pk)
        cursor.execute(update_sql, params)

        if cursor.rowcount == 0:
            insert_cols = [ctx.primary_key, ctx.output_col]
            insert_vals = [pk, result]
            if ctx.record_update_time:
                insert_cols.append("update_time")
                insert_vals.append(update_time)

            insert_sql = f"""
                INSERT INTO {quote_column(ctx.target_table)} ({', '.join(quote_column(c) for c in insert_cols)})
                VALUES ({', '.join(['?'] * len(insert_cols))})
            """
            cursor.execute(insert_sql, insert_vals)


def upsert_multi_values(ctx, cursor, pk, result_map: dict, is_sqlite, update_time=None):
    """一次 upsert 多個輸出欄位（for multi-stage writeback rules）。"""
    if not isinstance(result_map, dict) or not result_map:
        return
    cols = [str(k).strip() for k in result_map.keys() if str(k).strip()]
    if not cols:
        return

    if is_sqlite:
        insert_cols = [ctx.primary_key] + cols
        vals = [pk] + [result_map[c] for c in cols]
        if ctx.record_update_time:
            insert_cols.append("update_time")
            vals.append(update_time)
        set_clause = ", ".join([f"{quote_column(c)} = excluded.{quote_column(c)}" for c in cols])
        if ctx.record_update_time:
            set_clause += ", update_time = excluded.update_time"
        insert_sql = f"""
            INSERT INTO {quote_column(ctx.target_table)} ({', '.join(quote_column(c) for c in insert_cols)})
            VALUES ({', '.join(['?'] * len(insert_cols))})
            ON CONFLICT({quote_column(ctx.primary_key)}) DO UPDATE SET {set_clause}
        """
        cursor.execute(insert_sql, vals)
    else:
        set_expr = ", ".join([f"{quote_column(c)} = ?" for c in cols])
        params = [result_map[c] for c in cols]
        if ctx.record_update_time:
            set_expr += ", update_time = ?"
            params.append(update_time)
        update_sql = f"""
            UPDATE {quote_column(ctx.target_table)}
            SET {set_expr}
            WHERE {quote_column(ctx.primary_key)} = ?
        """
        cursor.execute(update_sql, params + [pk])

        if cursor.rowcount == 0:
            insert_cols = [ctx.primary_key] + cols
            insert_vals = [pk] + [result_map[c] for c in cols]
            if ctx.record_update_time:
                insert_cols.append("update_time")
                insert_vals.append(update_time)
            insert_sql = f"""
                INSERT INTO {quote_column(ctx.target_table)} ({', '.join(quote_column(c) for c in insert_cols)})
                VALUES ({', '.join(['?'] * len(insert_cols))})
            """
            cursor.execute(insert_sql, insert_vals)
