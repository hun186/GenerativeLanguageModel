#sql_mode/metrics/metering.py
from czjLLM.prompt_pipeline.pipeline_controller import ItemsRegistry, meter_path_init, meter_init

def init_meter(ctx):
    registry = ItemsRegistry()
    meter_fn = meter_path_init(ctx)
    thresholds = meter_init(
        meter_fn, ctx,
        low=getattr(ctx, "load_low_watermark", None),
        high=getattr(ctx, "load_high_watermark", None)
    )
    low  = thresholds["thresholds"]["low"]
    high = thresholds["thresholds"]["high"]
    return registry, meter_fn, low, high
    
# === 新增：查 outstanding（pending+running）===
def outstanding_now(meter_fn: str) -> int:
    """
    讀取 meter 檔，回傳目前 outstanding（pending+running）。
    讀不到或欄位缺失時回傳 0（安全預設）。
    """
    try:
        m = meter_read(meter_fn)
        q = m.get("queue", {}) or {}
        return int(q.get("pending", 0) or 0) + int(q.get("running", 0) or 0)
    except Exception:
        return 0

# （選配）方便觀測用的快照
def queue_snapshot(meter_fn: str) -> dict:
    try:
        m = meter_read(meter_fn)
        q = m.get("queue", {}) or {}
        return {
            "pending":  int(q.get("pending", 0) or 0),
            "running":  int(q.get("running", 0) or 0),
            "finished": int(q.get("finished", 0) or 0),
        }
    except Exception:
        return {"pending": 0, "running": 0, "finished": 0}