"""SQL mode public facade (imports are lazy so focused adapters stay lightweight)."""

def __getattr__(name):
    if name in {"load_sql_cfg", "InteractivePolicy", "NonInteractivePolicy"}:
        from .config import config_loader
        return getattr(config_loader, name)
    if name == "run_pipeline":
        from .runtime.orchestrator import run_pipeline
        return run_pipeline
    if name == "SQLiteAdapter":
        from .adapters.sqlite_adapter import SQLiteAdapter
        return SQLiteAdapter
    if name == "MSSQLAdapter":
        from .adapters.mssql_adapter import MSSQLAdapter
        return MSSQLAdapter
    raise AttributeError(name)

__all__ = [
    "run_pipeline",
    "load_sql_cfg", "InteractivePolicy", "NonInteractivePolicy",
    "SQLiteAdapter", "MSSQLAdapter",
]
