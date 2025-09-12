# tests/test_excel_sink.py
import pandas as pd
from openpyxl import load_workbook
from czjLLM.sql_mode.runtime.sinks.excel_sink import ExcelSink

def test_excel_sink_preserve_other_sheets(tmp_path):
    xlsx = tmp_path / "out.xlsx"
    # 先建立含 two sheets
    with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
        pd.DataFrame({"A":[1]}).to_excel(w, index=False, sheet_name="Sheet1")
        pd.DataFrame({"B":[2]}).to_excel(w, index=False, sheet_name="KeepMe")

    class Ctx: pass
    ctx = Ctx()
    ctx.output_col = "OPA"; ctx.input_col="Text"; ctx.record_update_time=True
    ctx.flatten_json_output=False; ctx.primary_key="row_id"

    # 建立輸入檔
    df = pd.DataFrame({"Text":["x"], "OPA":[""], "row_id":[0]})
    df.to_excel(xlsx, index=False, sheet_name="Sheet1")

    sink = ExcelSink(ctx, input_path=str(xlsx), output_path=str(xlsx), flush_main_every=1, flush_sub_every=1)
    sink.open()
    sink.write_main(pk=0, result_text="ok", update_time="2025-01-01 00:00:00")
    sink.close()

    wb = load_workbook(xlsx)
    assert "KeepMe" in wb.sheetnames, "other sheet should be preserved"
    sh = wb["Sheet1"]
    assert sh["A1"].value == "Text"
