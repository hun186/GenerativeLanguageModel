通訊簡訊拼裝三階段流程（gpt-oss 120b）

一、執行順序

1. SMS_Integration_Stage_1_GPTOSS120B.txt
   輸入：完整原始簡訊資料。
   輸出：DraftOccurrences、RawIDAssignments、UnresolvedFragments、CoverageAudit。

2. SMS_Integration_Stage_2_GPTOSS120B.txt
   輸入：
   （1）與第一階段相同的完整原始簡訊資料。
   （2）第一階段完整 JSON 輸出。
   輸出：Messages、UnresolvedOccurrences、RawIDDisposition、AuditSummary。

3. SMS_Integration_Stage_3_GPTOSS120B.txt
   輸入：第二階段完整 JSON 輸出。
   輸出：最終模板 JSON Array。

二、設計重點

1. 第一階段不做精簡、同文去重或模板收攏，強制覆蓋全部 RawID。
2. 第二階段重新查看原始資料，以敵對方式稽核第一階段，處理漏段、錯配、廣播及完全同文收攏。
3. 第三階段只處理已確認完整正文，不再重新拼接。
4. Address、時間、Channel 均為軟性證據，SMSContent 的直接文字銜接優先。
5. 不需要額外的程式語意拼接；代理人只需把前一階段輸出帶入下一階段。

三、第三階段新增欄位

為配合人工複核，最終輸出較舊版增加：

* IsBroadcastLike
* BroadcastReason
* ReviewPriority
* ReviewReasons

若下游程式使用固定舊 Schema，可從第三階段的輸出欄位及 JSON 範例中刪除上述四個欄位，其餘流程不受影響。
