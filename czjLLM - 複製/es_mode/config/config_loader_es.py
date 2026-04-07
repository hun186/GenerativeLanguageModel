# czjLLM/es_mode/config/config_loader_es.py
from czjLLM.config_ui.interactive_config_loader import load_es_config_interactively

class InputPolicy:
    """策略型 API，暫未啟用。"""
    pass

class InteractivePolicy(InputPolicy):
    pass

class NonInteractivePolicy(InputPolicy):
    def __init__(self, args):
        self.args = args

def load_es_cfg(ctx, get_param, args, policy: InputPolicy):
    """
    載入 ES 設定，先沿用互動式載入器。
    若 args 有指定非互動設定，可擴充此處。
    """
    return load_es_config_interactively(ctx.PGMSubDir, get_param, ctx)
