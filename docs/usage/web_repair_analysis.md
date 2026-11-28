# WEB-06B repair classification

The existing QualityAccumulator is the authority for exact per-run
successful repair and class counts. Unreported historical successes
are not backfilled. COMPARISON_UNAVAILABLE is a reported category but
not a comparable sample. Classification coverage and comparable coverage
use successful repair events as denominator, not initial invalid JSON.
The recent bounded ring contains at most 50 classified successes; only
validated numeric aggregates and fixed error-kind categories leave the
background monitor. No per-case IDs, hints, timestamps, prompt/response or
raw repair pairs. Recent distributions are not whole-run distributions:
each metric has its own count; literal matching excludes tail and
unavailable placeholders, key and length change exclude unavailable.
Signed changes are repaired minus original; error position is approximate.
Lexical candidates cannot prove semantic fidelity, truncation or key
preservation. Missing/invalid projection is unavailable, not a guessed
zero; the main quality counters remain independently usable. No writer,
repair policy or capture setting changes. Project context sync required
before ready/merge after parent stack.
