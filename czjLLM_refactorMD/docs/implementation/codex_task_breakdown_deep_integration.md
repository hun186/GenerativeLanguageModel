# Codex Execution Plan: Deep Integration Version

## Phase 0 — Mandatory repo scan
先盤點：
- prompt construction
- LLM call sites
- extraction flow
- chunking flow
- merge flow
- parallel / multiprocessing path
- dispatcher / routing / scheduling
- monitoring / tracing / logging
- handlers / row processors / downstream writers

## Phase 1 — Pipeline Foundation
1. PipelineContext
2. pipeline types
3. pipeline controller
4. pipeline config
5. pipeline utils

## Phase 2 — Runtime Integration Skeleton
6. runtime adapter / wrapper
7. preserve monitoring metadata
8. verify downstream compatibility

## Phase 3 — DocType Classification
9. add DocType-Classification task setting
10. build doctype helper
11. create classification step

## Phase 4 — Chunk Summary
12. create chunk summary step
13. make it runnable via existing chunk execution path

## Phase 5 — Prompt Refactor
14. base prompt
15. overlay prompts
16. prompt builder

## Phase 6 — Extraction
17. create extraction step as wrapper around existing extraction
18. inject doc_type context
19. preserve schema
20. run through existing chunk runtime path

## Phase 7 — Merge
21. base strategy
22. event / interview / profile / issue / report / legal / mixed strategies
23. merge selector
24. merge step

## Phase 8 — Landing
25. register pipeline
26. expose `run_pipeline()`
27. integrate with existing dispatcher / task runner

## Phase 9 — Testing
28. mock/fake LLM
29. smoke test
30. PipelineContext flow test
31. output wrapper test
32. schema compatibility test
33. merge strategy selection test
34. runtime integration test
35. backward compatibility test

## Success criteria
- no schema break
- no duplicate system
- runtime integration is real
- old system still works
