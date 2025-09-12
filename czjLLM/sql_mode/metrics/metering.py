from prompt_pipeline.pipeline_controller import ItemsRegistry, meter_path_init, meter_init

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