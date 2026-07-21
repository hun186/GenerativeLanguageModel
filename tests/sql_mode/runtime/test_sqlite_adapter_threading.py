import importlib.util
import sqlite3
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _load_sqlite_adapter_class():
    repo_root = Path(__file__).resolve().parents[3]
    package_name = "czjLLM.sql_mode.adapters"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(repo_root / "czjLLM" / "sql_mode" / "adapters")]
        sys.modules[package_name] = package

    base_name = f"{package_name}.base_adapter"
    if base_name not in sys.modules:
        base_spec = importlib.util.spec_from_file_location(
            base_name, repo_root / "czjLLM" / "sql_mode" / "adapters" / "base_adapter.py"
        )
        base_mod = importlib.util.module_from_spec(base_spec)
        sys.modules[base_name] = base_mod
        base_spec.loader.exec_module(base_mod)

    module_name = f"{package_name}.sqlite_adapter"
    spec = importlib.util.spec_from_file_location(
        module_name, repo_root / "czjLLM" / "sql_mode" / "adapters" / "sqlite_adapter.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.SQLiteAdapter


SQLiteAdapter = _load_sqlite_adapter_class()


def _create_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE tgt (id TEXT PRIMARY KEY, result TEXT)')
        conn.executemany(
            'INSERT INTO tgt (id, result) VALUES (?, ?)',
            [("1", "done"), ("2", None), ("3", "")],
        )


def test_sqlite_adapter_pending_recheck_can_run_from_worker_threads(tmp_path):
    db_path = tmp_path / "threaded.sqlite3"
    _create_db(db_path)
    adapter = SQLiteAdapter({"server": str(db_path)}).connect()
    try:
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(
                executor.map(
                    lambda pk: adapter.is_row_pending(
                        tgt_table="tgt",
                        pk="id",
                        pk_value=pk,
                        output_cols=["result"],
                    ),
                    ["1", "2", "3"],
                )
            )
        assert results == [False, True, True]
    finally:
        adapter.close()


def test_sqlite_adapter_pending_recheck_runs_after_main_thread_iteration(tmp_path):
    db_path = tmp_path / "iteration_then_threaded.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute('CREATE TABLE src (id TEXT PRIMARY KEY, body TEXT)')
        conn.execute('CREATE TABLE tgt (id TEXT PRIMARY KEY, result TEXT)')
        conn.executemany(
            'INSERT INTO src (id, body) VALUES (?, ?)',
            [("1", "text"), ("2", "text")],
        )
        conn.executemany(
            'INSERT INTO tgt (id, result) VALUES (?, ?)',
            [("1", None), ("2", "done")],
        )

    adapter = SQLiteAdapter({"server": str(db_path)}).connect()
    try:
        rows = list(
            adapter.select_pending_rows(
                src_table="src",
                tgt_table="tgt",
                pk="id",
                input_col="body",
                output_cols=["result"],
                record_update_time=False,
            )
        )
        assert [row[0] for row in rows] == ["1"]

        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(
                adapter.is_row_pending,
                tgt_table="tgt",
                pk="id",
                pk_value="2",
                output_cols=["result"],
            ).result() is False
    finally:
        adapter.close()
