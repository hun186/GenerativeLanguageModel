graph LR
    %% 樣式定義
    classDef db fill:#e1f5fe,stroke:#0277bd,stroke-width:2px;
    classDef stage fill:#fff,stroke:#333,stroke-width:1px,stroke-dasharray: 5 5;
    classDef raw_col fill:#eceff1,stroke:#546e7a,stroke-width:1px;
    classDef final_col fill:#ffebee,stroke:#b71c1c,stroke-width:1px;
    classDef flatten_col fill:#e8f5e9,stroke:#1b5e20,stroke-width:1px;

    %% SQLite 資料庫概念
    subgraph DB [SQLite 終端資料表 (Result Table)]
        
        subgraph DB_RAW [原始/輸入欄位]
            Col_File[File (Text)]
            Col_Score[InfoScoreSum (Number)]
        end

        subgraph DB_STAGE [階段持久化欄位 (Source for WB)]
            Col_WB_0[File_score_route]
            Col_WB_1[File_route]
            Col_WB_2[File_result (JSON string)]
            Col_WB_3[File_audit_json (JSON string)]
        end

        subgraph DB_FLATTEN [JSON 展開欄位 (Flattened)]
            %% Rule 2 fields
            F_R2_route[route]
            F_R2_name[formalName]
            F_R2_domain[functionalDomain]
            %% ... 其他欄位
            
            %% Rule 3 fields
            F_R3_tag[auditTag]
            F_R3_ver[auditVersion]
        end
    end

    %% 框架處理程序
    Framework{{czjLLM 框架處理}}

    %% 輸入連線
    Col_File --> Framework
    Col_Score --> Framework

    %% 階段處理與寫回 (對應 sql_writeback_rules)
    Framework -->|Stage: score_route| Col_WB_0
    Framework -->|Stage: route| Col_WB_1
    Framework -->|Stage: extract| Col_WB_2
    Framework -->|Stage: audit_json| Col_WB_3

    %% 展開處理 (對應 sql_flatten_writeback_rules)
    Col_WB_2 -->|Flatten (Rule 2: Enabled)| DB_FLATTEN
    Col_WB_3 -->|Flatten (Rule 3: Enabled)| DB_FLATTEN
    
    %% 沒啟用的展開 (用虛線表示)
    Col_WB_0 -.->|Rule 0: Disabled| Framework
    Col_WB_1 -.->|Rule 1: Disabled| Framework

    %% 樣式應用
    class DB db;
    class Framework process;
    class Col_File,Col_Score raw_col;
    class Col_WB_0,Col_WB_1,Col_WB_2,Col_WB_3 final_col;
    class F_R2_route,F_R2_name,F_R2_domain,F_R3_tag,F_R3_ver flatten_col;