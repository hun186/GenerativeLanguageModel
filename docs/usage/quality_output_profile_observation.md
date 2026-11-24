# Output Profile observation (#313)

The active ESSink exposes an explicit, local single-primary-field observation for the known built-in multidim_event profile. Existing sink JSON/envelope preparation is reused; the actual built-in callable is checked and used on a copy. The result is only a structural verdict and contract version, with no raw payload or exception text. Empty output, plugin/registry override, passthrough, disabled output, flattening or multi-field routing are unavailable. No buffer, ES write or retry policy change.

The version is an explicitly maintained label, not executable authentication; bump when built-in profile or sink preparation semantics change. A structural rejection does not prove a completed authorized repair, and acceptance does not prove source semantics or final writeback. Real source, complete execution/rule identity and sink reconciliation are separate gates. Existing mandatory Linux and Windows ES sink multifield suite covers this observation.
