# 清除 `es_json_multistage_langroute_config.yaml` 在 Elasticsearch 的執行結果

本文說明如何透過 **Kibana → Dev Tools → Console** 清除 `czjLLM/yaml/es_json_multistage_langroute_config.yaml` 執行後寫回到 Elasticsearch 文件的欄位，讓 doc 條目回到尚未跑過該 pipeline 的狀態。

> 注意：Kibana 的 **Discover / Discovery** 主要用來查詢與瀏覽文件，不能直接執行 `_update_by_query`。請改到 **Kibana → Dev Tools → Console** 執行本文的 Elasticsearch API 指令。

## 這支設定檔會寫回哪些欄位？

`es_json_multistage_langroute_config.yaml` 的主要輸出與寫回規則如下：

- `multidim_event_json`
- `multidim_event_json_meta`
- `route_audit_json`
- `route_audit_json_meta`
- `update_time_ai`：因為 YAML 內有 `record_update_time: true`，程式寫回時會在根層記錄 AI 更新時間。

其中 `es_writeback_rules` 指定主要寫回 index 為 `srp_test`。如果你的實際環境有改 index，請把以下指令中的 `srp_test` 換成你的目標 index。

本文範例使用 YAML 內設定的 pipeline hash：

```text
v3.2.2-es-multistage-rerun-test
```

## 建議流程

1. 先查會影響幾筆文件。
2. 確認數量合理後，再執行 `_update_by_query` 移除欄位。
3. 最後再查一次，確認欄位已清除。

## 1. 先用 pipeline hash 查詢影響筆數

建議優先使用 pipeline hash 限定這次 pipeline 的產物，避免誤刪其他流程留下的資料。

```json
GET srp_test/_count
{
  "query": {
    "bool": {
      "should": [
        {
          "term": {
            "multidim_event_json_meta.pipeline_hash": "v3.2.2-es-multistage-rerun-test"
          }
        },
        {
          "term": {
            "route_audit_json_meta.pipeline_hash": "v3.2.2-es-multistage-rerun-test"
          }
        }
      ],
      "minimum_should_match": 1
    }
  }
}
```

如果回傳的 `count` 符合預期，再進行下一步。

## 2. 清除這次 pipeline 產出的欄位

以下指令會移除：

- `multidim_event_json`
- `multidim_event_json_meta`
- `route_audit_json`
- `route_audit_json_meta`

```json
POST srp_test/_update_by_query?conflicts=proceed&refresh=true
{
  "script": {
    "lang": "painless",
    "source": """
      String[] fields = new String[] {
        'multidim_event_json',
        'multidim_event_json_meta',
        'route_audit_json',
        'route_audit_json_meta'
      };

      for (String f : fields) {
        if (ctx._source.containsKey(f)) {
          ctx._source.remove(f);
        }
      }
    """
  },
  "query": {
    "bool": {
      "should": [
        {
          "term": {
            "multidim_event_json_meta.pipeline_hash": "v3.2.2-es-multistage-rerun-test"
          }
        },
        {
          "term": {
            "route_audit_json_meta.pipeline_hash": "v3.2.2-es-multistage-rerun-test"
          }
        }
      ],
      "minimum_should_match": 1
    }
  }
}
```

## 3. 如果也要移除 `update_time_ai`

`update_time_ai` 是根層欄位。若它只由這次 pipeline 寫入，可以一起刪除；但如果其他流程也依賴或更新這個欄位，不建議刪除。

確定要讓文件更接近「完全沒跑過」的狀態時，可使用下列版本：

```json
POST srp_test/_update_by_query?conflicts=proceed&refresh=true
{
  "script": {
    "lang": "painless",
    "source": """
      String[] fields = new String[] {
        'multidim_event_json',
        'multidim_event_json_meta',
        'route_audit_json',
        'route_audit_json_meta',
        'update_time_ai'
      };

      for (String f : fields) {
        if (ctx._source.containsKey(f)) {
          ctx._source.remove(f);
        }
      }
    """
  },
  "query": {
    "bool": {
      "should": [
        {
          "term": {
            "multidim_event_json_meta.pipeline_hash": "v3.2.2-es-multistage-rerun-test"
          }
        },
        {
          "term": {
            "route_audit_json_meta.pipeline_hash": "v3.2.2-es-multistage-rerun-test"
          }
        }
      ],
      "minimum_should_match": 1
    }
  }
}
```

## 4. 若 pipeline hash 查不到結果

如果 pipeline hash 查詢結果是 0，但你確定文件內有該 pipeline 產出的欄位，可以改用欄位存在條件檢查。

### 4.1 先查有欄位的文件數

```json
GET srp_test/_count
{
  "query": {
    "bool": {
      "should": [
        { "exists": { "field": "multidim_event_json" } },
        { "exists": { "field": "multidim_event_json_meta" } },
        { "exists": { "field": "route_audit_json" } },
        { "exists": { "field": "route_audit_json_meta" } }
      ],
      "minimum_should_match": 1
    }
  }
}
```

### 4.2 清掉所有有這些欄位的文件

> 危險：這個版本不限 pipeline hash，會清掉 `srp_test` 裡所有符合欄位存在條件的文件產物。只有在你確認這些欄位都是要清除的結果時才使用。

```json
POST srp_test/_update_by_query?conflicts=proceed&refresh=true
{
  "script": {
    "lang": "painless",
    "source": """
      String[] fields = new String[] {
        'multidim_event_json',
        'multidim_event_json_meta',
        'route_audit_json',
        'route_audit_json_meta'
      };

      for (String f : fields) {
        if (ctx._source.containsKey(f)) {
          ctx._source.remove(f);
        }
      }
    """
  },
  "query": {
    "bool": {
      "should": [
        { "exists": { "field": "multidim_event_json" } },
        { "exists": { "field": "multidim_event_json_meta" } },
        { "exists": { "field": "route_audit_json" } },
        { "exists": { "field": "route_audit_json_meta" } }
      ],
      "minimum_should_match": 1
    }
  }
}
```

## 5. 執行後確認

清除後再查一次欄位是否仍存在：

```json
GET srp_test/_count
{
  "query": {
    "bool": {
      "should": [
        { "exists": { "field": "multidim_event_json" } },
        { "exists": { "field": "multidim_event_json_meta" } },
        { "exists": { "field": "route_audit_json" } },
        { "exists": { "field": "route_audit_json_meta" } }
      ],
      "minimum_should_match": 1
    }
  }
}
```

如果回傳 `count: 0`，表示上述輸出欄位已清除。

## 6. 關於 `generic-result-index`

YAML 裡 `non_zh` route 有設定 `tgt_index: generic-result-index`。如果你的執行結果也寫到了 `generic-result-index`，請先查詢確認內容：

```json
GET generic-result-index/_count
{
  "query": {
    "match_all": {}
  }
}
```

不要直接刪除整個 `generic-result-index`，除非你確定裡面都是可移除的測試資料。

## 補充：為什麼要清 meta 欄位？

後續 rerun / pending query 會參考輸出欄位與 meta 欄位判斷文件是否已處理、是否需要重跑。若只刪主輸出、不刪 meta，文件狀態可能看起來不一致。因此建議主輸出與對應 meta 一起清除。
