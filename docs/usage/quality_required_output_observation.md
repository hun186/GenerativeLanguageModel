# Required-output rule observation (#313)

Both existing ES pending-policy adapters expose an explicit read-only observation of enabled, supported output-local checks. The actual path resolver and shared evaluator are reused. The canonical check snapshot supplies both the versioned configuration digest and the validation result. Disabled, malformed, unknown or external-field checks are unavailable; existing permissive freshness behavior is unchanged.

The digest includes the effective path, validator, date format, minimum count and explicit empty-events opt-in; evaluator semantic changes require a contract version bump. This is only the required-output component, not full Output Profile identity or proof of a completed LLM repair. No automatic observation, retry accounting, source mutation or dispatch changes. Real effective configuration and authenticated attempt/sink evidence remain separate gates.
