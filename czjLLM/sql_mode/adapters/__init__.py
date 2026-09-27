def __getattr__(name):
    if name == "SQLiteAdapter":
        from .sqlite_adapter import SQLiteAdapter
        return SQLiteAdapter
    if name == "MSSQLAdapter":
        from .mssql_adapter import MSSQLAdapter
        return MSSQLAdapter
    raise AttributeError(name)

__all__ = ["SQLiteAdapter", "MSSQLAdapter"]
