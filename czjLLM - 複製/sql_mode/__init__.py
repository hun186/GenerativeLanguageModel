# re-export 常用入口，讓外部程式碼可維持簡潔匯入
from .config.config_loader import load_sql_cfg, InteractivePolicy, NonInteractivePolicy
from .runtime.orchestrator import run_pipeline

# 若外部偶爾會自己 new adapter，可選擇 re-export
from .adapters.sqlite_adapter import SQLiteAdapter
from .adapters.mssql_adapter import MSSQLAdapter

__all__ = [
    "run_pipeline",
    "load_sql_cfg", "InteractivePolicy", "NonInteractivePolicy",
    "SQLiteAdapter", "MSSQLAdapter",
]
