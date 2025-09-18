#PackageImport.py
import os
from pathlib import Path

def set_working_dir_to(target_folder_name):
    """
    從目前檔案所在路徑向上搜尋，直到找到名稱為 target_folder_name 的資料夾，
    並將工作目錄切換到該目錄，同時回傳從該目錄到原始工作目錄的相對路徑 (PGMSubDir)。
    """
    # 取得移動前的工作目錄
    original_dir = os.getcwd()
    
    # 以 __file__ 所在的目錄作為搜尋起點
    current_dir = os.path.abspath(os.path.dirname(__file__))
    
    while True:
        if os.path.basename(current_dir) == target_folder_name:
            # 計算從目標資料夾到原始工作目錄的相對路徑
            relative_path = os.path.relpath(original_dir, current_dir)
            os.chdir(current_dir)
            print("工作目錄已切換至:", os.getcwd())
            return relative_path
        next_dir = os.path.dirname(current_dir)
        if next_dir == current_dir:
            raise RuntimeError(f"找不到名稱為 '{target_folder_name}' 的資料夾")
        current_dir = next_dir

def get_relative_path_from_root(current_file: Path, root_name: str = "TopicClassification"):
    """
    傳回三個值：
    - 相對於 root_name 的路徑（如 Risk/RiskAnalyzer）
    - root_name 的絕對路徑
    - 當前腳本的父目錄絕對路徑

    Parameters:
    ----------
    current_file : Path
        傳入 __file__ 或其他檔案路徑
    root_name : str
        尋找的根目錄資料夾名稱，例如 "TopicClassification"

    Returns:
    -------
    relative_path : Path
        相對於 root_name 的子資料夾路徑
    root_dir : Path
        根目錄的完整絕對路徑
    current_dir : Path
        傳入的檔案所在的目錄（即 current_file.parent）
    """
    current_file = current_file.resolve()
    current_dir = current_file.parent

    for parent in current_dir.parents:
        if parent.name == root_name:
            relative_path = current_dir.relative_to(parent)
            return relative_path, parent, current_dir

    raise RuntimeError(f"❌ 無法從 {current_file} 中找到名為 '{root_name}' 的父層資料夾")
    
class PackageImporter:
    def proc():
        import sys
        import glob
        ModPaths = []
        #ModPaths.extend(glob.glob("C:/Users/*/Documents/PythonModule"))
        ModPaths.extend([
            "D:/shared/PythonModule",
            "Z:/PythonModule",
            "PythonModule",
            "../PythonModule",
            "../../PythonModule",
            "../../../PythonModule",
            "../../../../PythonModule",
            "../../../../../PythonModule",
            "../../../../../../PythonModule",
            "./../",
            #"../../TopicClassification",
            #"../../TopicClassification_WeiTech",
            #"/mntCZJ/TopicClassification",
            #"/mntCZJ/TopicClassification_WeiTech",
            "./",
            #".",
            #"D:\shared\TopicClassification",
            ])
        for ModulePath in ModPaths:
            sys.path.append(ModulePath)
        #print(sys.path)
        #import os