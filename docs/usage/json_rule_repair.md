# Conservative JSON repair candidates (phase 1)

Two pure functions, not yet called by live Workers. Existing model calls, validation, retry/split, capture and sinks stay unchanged.

| Function | Allowed change | Refusal |
| --- | --- | --- |
| `repair_generic_json(raw)` | Leading BOM, single full Markdown JSON fence, lexically external trailing commas | Already valid input, arbitrary prose, scalars, duplicate keys, non-finite numbers, invalid escape, incomplete structure, budget exceeded |
| `repair_multidim_evidence_quotes(raw, source)` | Insert backslash before unescaped quote only at array[i].evidence_snippets[j].text, with exact decoded substring evidence | All other paths, legal original closing delimiters, no/multiple source-supported boundaries, malformed remainder, incomplete search, unknown source |

Return immutable candidate (text omitted from repr, fixed rule labels and edit count) or None. No I/O, logging, extra model call, pretty-print, or writeback. Strict final decoder rejects duplicates and non-finite values. Size 262144 chars, nesting 64, edits 32, per-evidence boundary search 4096 chars. Candidate is not proof of semantic intent or completeness.

Next gates: bind explicit task configuration to exact dispatched input, preserve original on refusal, provider-length guard and downstream validation, distinguish repair method in Quality events/GUI, reuse bounded private capture, private A/B before activation. Existing Worker strips Markdown markers globally before handle_json_output; do not claim safe wrapper semantics until integration reviewed. No default behavior change.

Run `python -m pytest -q tests/test_json_rule_repair.py` with project requirements installed. Synthetic fixtures; no production ES/SQL/Ollama or private source.
