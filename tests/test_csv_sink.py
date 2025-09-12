# tests/test_csv_sink.py
import pandas as pd
from czjLLM.tabular_mode.runtime.sinks.csv_sink import CSVSink

def test_csv_sink_types(tmp_path):
    csv = tmp_path / "m.csv"
    pd.DataFrame({"k":[1], "Text":["hi"], "OPA":[""]}).to_csv(csv, index=False)

    class Ctx: pass
    ctx = Ctx(); ctx.output_col="OPA"; ctx.input_col="Text"
    ctx.record_update_time=True; ctx.primary_key="k"; ctx.flatten_json_output=False

    s = CSVSink(ctx, main_csv=str(csv), flush_main_every=1)
    s.open()
    s.write_main(pk=1, result_text='{"x":1}', update_time="2025-02-02 03:04:05")
    s.close()

    out = pd.read_csv(csv)
    assert out.loc[0, "OPA"] == '{"x":1}'
    assert isinstance(out.loc[0, "OPA"], str)
    assert out.loc[0, "update_time"].startswith("2025-02-02")
