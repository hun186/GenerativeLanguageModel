        sql_cfg = load_sql_config_interactively(ctx.PGMSubDir, get_param, ctx)
        # === 智慧補齊資訊 ===
        server = sql_cfg.get("server", "").strip()
        if not server:
            server = input("🔹 請輸入 server（可為 IP 或 SQLite 檔案路徑），注意如果是SQLite檔案相對路徑，目前目錄為TopicClassification：").strip()
        
        # 根據 server 判斷使用 SQLite 或 SQL Server
        # 本地 sqlite 檔案模式
        if is_sqlite_path(server):
            ctx.sqlite_path = server
            ctx.sql_table = sql_cfg.get("table_name") or input("📋 請輸入 SQLite 表格名稱：").strip()
            ctx.primary_key = sql_cfg.get("primary_key", "")
            conn = sqlite3.connect(ctx.sqlite_path)
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({ctx.sql_table})")
            columns = [row[1] for row in cursor.fetchall()]
            conn.close()
            is_sqlite = True
        else:
        # 遠端 SQL Server 模式
            ctx.sql_connection_string = build_sql_connection_string(sql_cfg)
            conn = pyodbc.connect(ctx.sql_connection_string)
            ctx.sql_table = sql_cfg.get("table_name") or input("📋 請輸入資料表名稱：").strip()        
            ctx.primary_key = sql_cfg.get("primary_key", "")
            cursor = conn.cursor()
            cursor.execute(f"SELECT TOP 1 * FROM {ctx.sql_table}")
            columns = [desc[0] for desc in cursor.description]
            conn.close()
            is_sqlite = False
    
        ctx.reset_output = sql_cfg.get("reset_output", None)
        ctx.reset_confirm_code = sql_cfg.get("reset_confirm_code",None)
    
        if ctx.reset_output is None:
            ctx.reset_output = OptionSelector(
                options={"no": "否（僅處理尚未有結果的列）", "yes": "是（清空所有資料重新處理）"},
                question=f"⚠️ 是否要重設 {ctx.output_col} 欄位的所有資料？",
                default="no"
            ).proc()
            ctx.reset_output = True if ctx.reset_output == "yes" else False
        # 若有預先設定驗證碼，則跳過輸入
        if ctx.reset_output:
            if ctx.reset_confirm_code is not None:
                user_input = ctx.reset_confirm_code
            else:
                code = str(random.randint(10000, 99999))
                print(f"🔐 為避免誤操作，請輸入以下驗證碼以繼續：{Fore.YELLOW}{code}{Style.RESET_ALL}")
                user_input = input("請輸入驗證碼：").strip()
                if user_input != code:
                    print("❌ 驗證碼錯誤，取消重設。")
                    ctx.reset_output = False
            
        ctx.target_table = sql_cfg.get("target_table")
        #print("ctx",ctx)
        if not ctx.target_table:
            ctx.target_table = input(f"💾 請輸入目標資料表名稱（預設為 {ctx.sql_table}）：").strip()
            if not ctx.target_table:
                ctx.target_table = ctx.sql_table
                
        # === 主鍵 / 輸入 / 輸出欄位確認 ===
        if ctx.primary_key not in columns:
            ctx.primary_key = OptionSelector(
                options={col: "" for col in columns},
                question="🔑 請選擇主鍵欄位："
            ).proc()
    
        ctx.input_col = get_param("input_col", sql_cfg.get("input_col", ""))
        if ctx.input_col not in columns:
            ctx.input_col = OptionSelector(
                options={col: "" for col in columns},
                question="📝 請選擇輸入欄位："
            ).proc()
    
     
        ctx.output_col = get_param("output_col", sql_cfg.get("output_col", ""))
        if not ctx.output_col:
            ctx.output_col = input(f"💾 請輸入輸出欄位名稱（預設為 {ctx.input_col}_result）：").strip()
            if not ctx.output_col:
                ctx.output_col = ctx.input_col + "_result"
        
        ctx.record_update_time = get_param("record_update_time")
        if ctx.record_update_time is None:
            record_update_time = input("⏱️ 是否在每筆更新時記錄 update_time？(Y/n)：").strip().lower()
            ctx.record_update_time = (record_update_time != "n")
                
        ctx.flatten_json_output = get_param("flatten_json_output")
        ctx.allowed_output_fields = get_param("allowed_output_fields")
        # 只有在 CLI 模式下才詢問JSON展平
        if not args.config:
            if not ctx.flatten_json_output:
                flatten = input("🔧 是否將 JSON 結果展平成多個欄位？(y/N)：").strip().lower()
                ctx.flatten_json_output = flatten == "y"
    
            if ctx.flatten_json_output:
                if not ctx.allowed_output_fields:
                    raw_fields = input("📝 請輸入要寫入的 JSON 欄位名稱（以逗號分隔，例如 summary,score）：").strip()
                    ctx.allowed_output_fields = [f.strip() for f in raw_fields.split(",") if f.strip()]
                # 詢問是否也保留原始結果
                save_raw_output = input("📦 是否同時將原始 JSON 結果寫入主欄位（作為備查）？(y/N)：").strip().lower()
                ctx.save_raw_output_when_flatten = save_raw_output == "y"
                # 詢問是否也保留原始輸
                save_raw_input = input("📦 是否同時將原始輸入寫入子表（作為備查）？(y/N)：").strip().lower()
                ctx.save_raw_input_when_flatten = save_raw_input == "y"
        # 避免輸入欄位與輸出欄位相同
        if ctx.sql_table.strip().lower() == ctx.target_table.strip().lower():
            if ctx.input_col == ctx.output_col:
                print(f"⚠️ 輸入欄位（{ctx.input_col}）與輸出欄位相同，這可能會導致原始資料被覆蓋。")
                confirm_same_col = OptionSelector(
                    options={"no": "否，讓我重新選擇輸出欄位", "yes": "是，我確定要覆蓋原欄位"},
                    question="❗您是否確定要使用相同欄位作為輸出？",
                    default="no"
                ).proc()
                if confirm_same_col != "yes":
                    # 重新選擇輸出欄位
                    default_output_col = ctx.input_col + "_result"
                    ctx.output_col = OptionSelector(
                        options={col: "" for col in columns + [default_output_col]},
                        question="🔁 請重新選擇輸出欄位（建議使用不同名稱）："
                    ).proc()
            
        if not args.config:
            print_cli_usage_hint(ctx)
        
        if ctx.reset_output:
            reset_output_col_with_backup(ctx, is_sqlite)
        handle_sql_row_by_row(ctx,is_sqlite=is_sqlite)