# utils_manager/utils_sync.py
from __future__ import annotations
import os, sys, shutil, filecmp, datetime, inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple, List

# ---------- 小工具 ----------
def _now_stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

def _write_log(log_file: Path, msg: str) -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")

def _is_ignored(rel: Path) -> bool:
    parts = {p.lower() for p in rel.parts}
    if any(x in parts for x in {".git", "__pycache__", ".ipynb_checkpoints"}):
        return True
    if rel.suffix.lower() in {".pyc"}:
        return True
    return False

def _prepend_sys_path(p: Path):
    s = str(p.resolve())
    if s in sys.path:
        sys.path.remove(s)
    sys.path.insert(0, s)
    print(f"✔ 置頂模組路徑：{s}")

def _demote_sys_path(p: Path):
    s = str(p.resolve())
    if s in sys.path:
        sys.path.remove(s)
        sys.path.append(s)
        print(f"↘ 降權模組路徑：{s}")


# ---------- 路徑脈絡 ----------
@dataclass
class PathContext:
    project_root: Path      # TopicClassification
    app_root: Path          # GenerativeLanguageModel
    caller_dir: Path        # 例如 GenerativeLanguageModel/czjLLM
    rel_to_root: Path       # caller_dir 相對於 project_root
    rel_to_app: Path        # caller_dir 相對於 app_root

def init_path_context(
    root_name: str = "TopicClassification",
    app_name: str  = "GenerativeLanguageModel",
    markers: Iterable[str] = ("PackageImport.py",),
    max_levels: int = 15,
) -> PathContext:
    # 取得「外部」呼叫端檔案（跳過本檔 utils_sync.py）
    this_file = Path(__file__).resolve()
    caller_file = None
    for fr in inspect.stack()[1:]:
        f = Path(fr.filename).resolve()
        if f != this_file:
            caller_file = f
            break
    if caller_file is None:
        caller_file = this_file
    start_dir = caller_file.parent

    # ---- 先以資料夾名稱向上找到 root_name ----
    current = start_dir
    project_root = None
    for _ in range(max_levels + 1):
        if current.name == root_name:
            project_root = current
            break
        if current.parent == current:
            break
        current = current.parent

    # ---- 找不到再用標記檔備援 ----
    if project_root is None:
        current = start_dir
        for _ in range(max_levels + 1):
            if any((current / m).exists() for m in markers):
                project_root = current
                break
            if current.parent == current:
                break
            current = current.parent

    if project_root is None:
        raise FileNotFoundError(
            f"找不到 root 目錄（name='{root_name}' 或標記檔 {tuple(markers)}）"
        )

    # 找 app_root（GenerativeLanguageModel）
    current = start_dir
    app_root = None
    for _ in range(max_levels + 1):
        if current.name == app_name:
            app_root = current
            break
        if current == project_root:
            candidate = project_root / app_name
            app_root = candidate if candidate.exists() else project_root
            break
        current = current.parent
    if app_root is None:
        app_root = project_root

    # 確保 root 在 sys.path
    abs_root = str(project_root.resolve())
    if abs_root not in sys.path:
        sys.path.insert(0, abs_root)
        print(f"✔ 模組路徑已加入：{abs_root}")

    try:
        rel_to_root = start_dir.relative_to(project_root)
    except ValueError:
        rel_to_root = Path("")
    try:
        rel_to_app = start_dir.relative_to(app_root)
    except ValueError:
        rel_to_app = Path("")

    return PathContext(
        project_root=project_root,
        app_root=app_root,
        caller_dir=start_dir,
        rel_to_root=rel_to_root,
        rel_to_app=rel_to_app,
    )



# ---------- 同步 ----------
def add_module_path(module_path: Path) -> None:
    p = str(Path(module_path).resolve())
    if p not in sys.path:
        sys.path.insert(0, p)
        print(f"✔ 已加入模組路徑：{p}")

def sync_shared_utils(
    source_dir: Path,
    target_dir: Path,
    backup_dir: Path,
    log_file: Path,
    *,
    delete_extraneous: bool = False,
    include_ext: Optional[Iterable[str]] = None,
    allow_missing: bool = False,
) -> None:
    source_dir = Path(source_dir).resolve()
    target_dir = Path(target_dir).resolve()
    backup_dir = Path(backup_dir).resolve()
    log_file   = Path(log_file).resolve()

    if not source_dir.exists():
        msg = f"來源不存在：{source_dir}"
        if allow_missing:
            _write_log(log_file, f"SkipSync: {msg}")
            print(f"⚠️ {msg}（allow_missing=True，略過同步）")
            return
        raise FileNotFoundError(msg)

    if include_ext is not None:
        include_ext = {e if e.startswith(".") else f".{e}" for e in (x.lower() for x in include_ext)}

    stamp = _now_stamp()

    # 新增 / 更新
    for root, _, files in os.walk(source_dir):
        root_path = Path(root)
        rel_dir   = root_path.relative_to(source_dir)
        if _is_ignored(rel_dir):  # 整個目錄忽略
            continue

        tgt_root = target_dir / rel_dir
        bkp_root = backup_dir / stamp / rel_dir
        tgt_root.mkdir(parents=True, exist_ok=True)

        for name in files:
            src_file = root_path / name
            rel_file = (rel_dir / name)
            if _is_ignored(rel_file):
                continue
            if include_ext is not None and src_file.suffix.lower() not in include_ext:
                continue

            tgt_file = tgt_root / name
            if tgt_file.exists():
                if not filecmp.cmp(src_file, tgt_file, shallow=False):
                    bkp_root.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(tgt_file, bkp_root / name)   # 備份
                    shutil.copy2(src_file, tgt_file)          # 覆蓋
                    _write_log(log_file, f"Updated: {rel_file.as_posix()}")
                    print(f"🔄 更新 {rel_file}")
            else:
                shutil.copy2(src_file, tgt_file)
                _write_log(log_file, f"Added: {rel_file.as_posix()}")
                print(f"➕ 新增 {rel_file}")

    # 刪除多餘
    if delete_extraneous and target_dir.exists():
        for root, _, files in os.walk(target_dir, topdown=False):
            root_path = Path(root)
            rel_dir   = root_path.relative_to(target_dir)

            for name in files:
                tgt_file = root_path / name
                rel_file = rel_dir / name
                if _is_ignored(rel_file):
                    continue
                if include_ext is not None and tgt_file.suffix.lower() not in include_ext:
                    continue
                src_file = source_dir / rel_file
                if not src_file.exists():
                    tgt_file.unlink(missing_ok=True)
                    _write_log(log_file, f"Removed: {rel_file.as_posix()}")
                    print(f"🗑️ 刪除 {rel_file}")

            # 來源也沒有、且成為空夾才刪
            if root_path.exists() and not any(root_path.iterdir()):
                src_dir = source_dir / rel_dir
                if not src_dir.exists():
                    root_path.rmdir()
                    _write_log(log_file, f"RemovedDir: {rel_dir.as_posix() or '.'}")
                    print(f"🗂️ 刪空目錄 {rel_dir or '.'}")

# ---------- 設定檔解析 ----------
def resolve_config_path(config_arg: str, ctx: PathContext) -> Path:
    p = Path(config_arg)
    if p.is_absolute() and p.exists():
        return p

    candidates = [
        Path(os.getcwd()) / config_arg,   # 目前工作目錄
        ctx.app_root / config_arg,        # ✅ App 根（GenerativeLanguageModel）
        ctx.caller_dir / config_arg,      # 呼叫端模組旁
        ctx.project_root / config_arg,    # 專案根
    ]
    for c in candidates:
        try_print = c.relative_to(ctx.project_root) if c.is_absolute() else c
        #print("paths_to_try", try_print)
        if c.exists():
            return c

    joined = "\n".join(str(x) for x in candidates)
    raise FileNotFoundError(f"找不到設定檔：{config_arg}\n已嘗試：\n{joined}")

# ---------- 一鍵就緒 ----------
def prepare_env(
    *,
    root_name: str = "TopicClassification",
    app_name: str  = "GenerativeLanguageModel",
    markers: Iterable[str] = ("PackageImport.py",),
    source_subdir: str = "PythonModule",
    target_subdir: str = "lib/PythonModule",
    backup_subdir: str = "backup_utils",
    log_filename: str = "sync_utils.log",
    include_ext: Optional[Iterable[str]] = {".py"},
    delete_extraneous: bool = True,
    allow_missing: bool = True,             # ✅ 預設允許缺來源
    add_generative_dir_to_syspath: bool = True,
    prefer_pgm_subdir: str = "app",
    config_arg: Optional[str] = None,
    skip_on_spawn_env: str = "UTILS_SYNC_DONE",
    expose_pythonmodule_package: bool = True,  # 若要支援 from PythonModule import ...
) -> Tuple[PathContext, Path, Path, Optional[Path]]:
    """
    回傳：(ctx_paths, PGMSubDir, utils_dir, config_path)
    - 來源不存在時不報錯，僅記錄 SkipSync 並繼續。（部署友善）
    """
    print("prepare_env",prepare_env)
    ctx_paths = init_path_context(root_name=root_name, app_name=app_name, markers=markers)

    project_root = ctx_paths.project_root
    source_dir = project_root / source_subdir
    target_dir = project_root / target_subdir
    backup_dir = project_root / backup_subdir
    log_file   = project_root / log_filename

    # 只在主程序同步一次；來源不存在則略過並寫 log
    first_time = os.environ.get(skip_on_spawn_env) != "1"
    if first_time:
        os.environ[skip_on_spawn_env] = "1"
        if source_dir.exists():
            sync_shared_utils(
                source_dir=source_dir,
                target_dir=target_dir,
                backup_dir=backup_dir,
                log_file=log_file,
                delete_extraneous=delete_extraneous,
                include_ext=include_ext,
                allow_missing=True,          # 就算中途被搬走也不炸
            )
        else:
            _write_log(log_file, f"SkipSync: source not found {source_dir}")
            print(f"⚠️ 略過同步：來源不存在 → {source_dir}")
    # 不論是否同步，都嘗試加入匯入路徑（用已帶版的 lib）
    if target_dir.exists():
        add_module_path(target_dir)          # 支援：from utils... / import utils
        if expose_pythonmodule_package:
            # 置頂 <root>/lib，讓 from PythonModule import ... 指向 lib 副本
            _prepend_sys_path(target_dir.parent)
            _demote_sys_path(project_root)
    else:
        print(f"⚠️ 未找到已同步目標：{target_dir}（若需 from PythonModule 匯入請確保此目錄存在）")

    if add_generative_dir_to_syspath:
        add_module_path(ctx_paths.app_root)

    PGMSubDir = ctx_paths.app_root if prefer_pgm_subdir == "app" else ctx_paths.caller_dir
    cfg_path = resolve_config_path(config_arg, ctx_paths) if config_arg else None
    return ctx_paths, PGMSubDir, target_dir, cfg_path
