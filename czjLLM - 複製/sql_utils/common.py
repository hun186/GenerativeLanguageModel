import platform
import subprocess
import getpass

def quote_column(col: str) -> str:
    return f"[{col.strip()}]"

def safe_sql_value(val):
    import math
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    if isinstance(val, str) and val.strip().lower() in ["nan", "none"]:
        return ""
    if isinstance(val, list):
        return ", ".join(str(v) for v in val)
    return val

def get_sql_driver_name():
    if platform.system() == "Windows":
        return "SQL Server"
    else:
        # Linux - 嘗試用 odbcinst 查出 driver 列表
        try:
            output = subprocess.check_output(['odbcinst', '-q', '-d'], encoding='utf-8')
            drivers = [line.strip('[]') for line in output.splitlines()]
            if "ODBC Driver 18 for SQL Server" in drivers:
                return "ODBC Driver 18 for SQL Server"
            elif "ODBC Driver 17 for SQL Server" in drivers:
                return "ODBC Driver 17 for SQL Server"
            else:
                print("⚠️ 找不到已安裝的 SQL Server ODBC driver，請確認是否已安裝。")
                return "ODBC Driver 18 for SQL Server"  # fallback 預設值
        except Exception as e:
            print(f"⚠️ 無法偵測 ODBC driver：{e}")
            return "ODBC Driver 18 for SQL Server"  # fallback 預設值

def build_sql_connection_string(sql_cfg: dict) -> str:
    server = sql_cfg.get("server") or input("🖥️ 請輸入伺服器位址：").strip()
    username = sql_cfg.get("username") or input("🔐 請輸入使用者名稱：").strip()
    password = sql_cfg.get("password") or getpass.getpass("🔐 請輸入密碼：")
    database_name = sql_cfg.get("database_name") or input("🗂️ 請輸入資料庫名稱：").strip()
    
    driver = get_sql_driver_name()
    
    conn_str = (
        f"DRIVER={{{driver}}};SERVER={server};"
        f"DATABASE={database_name};UID={username};PWD={password};"
    )
    if "ODBC Driver 1" in driver:
        conn_str += "Encrypt=yes;TrustServerCertificate=yes;"
    return conn_str