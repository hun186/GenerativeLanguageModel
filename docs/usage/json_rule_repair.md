# Conservative JSON repair (legacy single-stage Queue)

The two pure candidate functions are available through explicit Worker opt-in. Built-in tasks remain off by default. Ordinary model calls, retry/split, capture and sinks stay unchanged.

| Function | Allowed change | Refusal |
| --- | --- | --- |
| `repair_generic_json(raw)` | Leading BOM, single full Markdown JSON fence, lexically external trailing commas | Already valid input, arbitrary prose, scalars, duplicate keys, non-finite numbers, invalid escape, incomplete structure, budget exceeded |
| `repair_multidim_evidence_quotes(raw, source)` | Insert backslash before unescaped quote only at array[i].evidence_snippets[j].text, with exact decoded substring evidence | All other paths, legal original closing delimiters, no/multiple source-supported boundaries, malformed remainder, incomplete search, unknown source |

Return immutable candidate (text omitted from repr, fixed rule labels and edit count) or None. No I/O, logging, extra model call, pretty-print, or writeback. Strict final decoder rejects duplicates and non-finite values. Size 262144 chars, nesting 64, edits 32, per-evidence boundary search 4096 chars. Candidate is not proof of semantic intent or completeness.

The Worker preserves the invalid output for existing LLM repair on refusal, checks provider completion, applies the explicit slice validator and retains downstream document validation. The existing quality event can identify RULE_BASED repairs. GUI method totals and actual provider A/B remain follow-up work. No default behavior change.

Run `python -m pytest -q tests/test_json_rule_repair.py` with project requirements installed. Synthetic fixtures; no production ES/SQL/Ollama or private source.


### Explicit legacy single-stage task opt-in

In a trusted Python taskSetting entry, add `"json_rule_repair": {"generic": True}` and `"json_rule_slice_contract": "multidim_event_slice_v1"` for the current MultiDim profile, or use an importable module-level Python function implementing the task's actual slice contract and returning a strict bool. No dynamic import strings are accepted. Both are required; no built-in task is enabled by default. A context-local registry that differs from the renderer's task semantics declines activation. Only Linux/Windows legacy single-stage Queue dispatch is wired; multi-stage and direct file dispatch remain unchanged, as do document-wide required-output checks. The registered profile validates structure, not factual accuracy or completeness, and never substitutes its normalized payload for the candidate.


### Source-verified evidence quotes

Only the two pinned built-in MultiDim append-only renderers, with the registered `multidim_event_slice_v1` contract, may explicitly enable `"multidim_evidence_quotes": True` inside `json_rule_repair`. Generic repair remains a separate flag. A fresh legacy Queue generation must carry a verified source receipt from the Producer through its first actual claim; the successful API invocation must return a matching final-prompt receipt. The Worker consumes that receipt once and requires provider finish_reason="stop", exact source support, unambiguous allowed edits, complete strict JSON and the structural slice contract before accepting a candidate. A missing or invalid receipt disables source-based repair; generic repairs may still qualify independently when enabled. A failed rule leaves the malformed original for existing LLM repair. Requeue/restart/split generations without provenance, modified/truncated source, and unsupported tasks do not use source-based repair. No new raw-text retention. These are opt-in capabilities, not evidence that a production task has enabled them or that provider performance has improved.
