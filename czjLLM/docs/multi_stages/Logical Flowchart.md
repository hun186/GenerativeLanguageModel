graph TD
    %% 樣式定義
    classDef storage fill:#f9f,stroke:#333,stroke-width:2px;
    classDef process fill:#e1f5fe,stroke:#0277bd,stroke-width:1px,rx:5px,ry:5px;
    classDef decision fill:#fff9c4,stroke:#fbc02d,stroke-width:1px;
    classDef output fill:#c8e6c9,stroke:#2e7d32,stroke-width:1px,rx:10px,ry:10px;

    %% 輸入
    Input[(輸入資料列<br/>Source Row)] -->|讀取 InfoScoreSum| S1

    %% Stage 1: score_route
    subgraph ST1 [Stage 1: score_route]
        S1[LLM 分類器:<br/>判斷分數 > 300?]
    end
    S1 -->|輸出: high / low| R1{路由分支 1<br/>Route by score_route}

    %% Stage 2: route
    subgraph ST2 [Stage 2: route]
        R1 -->|low| S2_L[直接輸出:<br/>'other']
        R1 -->|high| S2_H[LLM 分類器:<br/>判斷是否為組織介紹?]
    end
    S2_L -->|輸出: other| R2{路由分支 2<br/>Route by route}
    S2_H -->|輸出: org / other| R2

    %% Stage 3: extract (並行概念，但在邏輯依賴上位於 route 之後)
    subgraph ST3 [Stage 3: extract]
        R2 -->|org| S3_O[呼叫外部任務:<br/>Organization Profile Analyzer]
        R2 -->|other| S3_T[LLM 回覆器:<br/>生成 'not_an_organization' JSON]
    end

    %% Stage 4: audit_json (並行概念)
    subgraph ST4 [Stage 4: audit_json]
        R2 -->|org| S4_O[LLM 回覆器:<br/>生成 'org_profile_path' JSON]
        R2 -->|other| S4_T[LLM 回覆器:<br/>生成 'non_org_path' JSON]
    end

    %% 最終結果匯集
    S3_O --> Result1[(File_result<br/>主要分析結果)]
    S3_T --> Result1
    S4_O --> Result2[(File_audit_json<br/>路徑審計)]
    S4_T --> Result2
    
    %% 持久化輸出的連線 (為了畫面整潔簡化，概念上它們也被儲存)
    S1 -.->|Persist| P1[(File_score_route)]
    S2_H -.->|Persist| P2[(File_route)]
    S2_L -.->|Persist| P2

    %% 應用樣式
    class Input storage;
    class S1,S2_H,S2_L,S3_O,S3_T,S4_O,S4_T process;
    class R1,R2 decision;
    class Result1,Result2,P1,P2 output;