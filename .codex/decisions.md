# 技術決策（Technical Decisions）

## Current Summary

- 

## Recent Changes

- 

## Archived History

- 


## 2026-06-25 pending running console is short-lived coordination state

- 決策：`pending_running_console.json` 只保存目前 running 與最近完成/釋放的短期觀察資訊；`last_finished` 預設保留 1 小時，不作為長期完成歷史。
- 理由：pending running console 的目的在於多程序派工前避免撞到正在 running 的 row/file；若保存所有 completed 紀錄，幾萬筆長期批次會造成 JSON 無限制膨脹。
- 後果：若中控檔損毀或被刪除，可重建並恢復後續 running 協調；短時間內可能降低避撞效果，但最終是否派工仍由 pending recheck / 目標輸出狀態決定。
