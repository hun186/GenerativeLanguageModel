# Large Audit incremental aggregation (WEB-05C1)

Web background monitor uses the same exact row accumulator as the legacy
snapshot reader. A refresh scans at most 4 MiB, up to the existing 512 MiB
canonical file bound, 200,000 retained rows, 4,096 heuristic groups. Only
complete logical CSV rows advance the cursor; incomplete tails and catch-up
show bytes scanned but no partial totals. An unchanged complete file reuses
the cached public result without re-sorting. Path/generation changes,
truncation, checkpoint mismatch, mutation during scan and errors discard
state. The append-only writer is the trust boundary: this is not a cryptographic
proof of every historical byte against arbitrary concurrent rewrites.
No raw text, paths or group identifiers are published; strict group keys
are hashed. Exact percentile storage and sorting remain bounded but not
constant memory; very large runs require a later explicitly approximate
or external-storage design. No physical long-run performance measured.
