import os

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
        import os