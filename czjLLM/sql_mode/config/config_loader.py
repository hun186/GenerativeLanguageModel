# sql_mode/config_loader.py
from czjLLM.config_ui.interactive_config_loader import load_sql_config_interactively

class InputPolicy:
    """預留策略型 API；此步先不啟用。"""
    pass

class InteractivePolicy(InputPolicy):
    pass

class NonInteractivePolicy(InputPolicy):
    def __init__(self, args):
        self.args = args

def load_sql_cfg(ctx, get_param, args, policy: InputPolicy):
    """
    先沿用你現有的互動式載入器，不改行為。
    後續若要支持 --config 非互動模式，再在此擴充。
    """
    return load_sql_config_interactively(ctx.PGMSubDir, get_param, ctx)
