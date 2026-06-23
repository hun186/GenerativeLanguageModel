# Project Memory

## Current Summary

- 

## Recent Changes

### 

-

## 2026-06-23 AGENTS.md 專案內容更新

- 任務目的：將從其他專案複製而來的 AGENTS.md 後半段改為符合本專案的工作指南。
- 主要修改內容：更新專案概覽、開發流程、優先工作路徑、搜尋原則、常用驗證指令與修改規範，移除 FastAPI / Elasticsearch RAG dashboard 等不屬於本專案的描述。
- 驗證結果：以 `python -m compileall czjLLM/pipeline czjLLM/row_processors czjLLM/utilities` 做語法層級檢查。
- 重要結論：本專案主要是 Python 多來源資料處理與 LLM 多階段分析框架，後續 Agent 應優先查看 pipeline、mode、YAML 設定與 LLM infrastructure 相關路徑。
