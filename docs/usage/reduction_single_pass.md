# Single-pass Reduction Engine configuration

This guide covers explicit, single-pass reduction at the existing combine boundary.
The Reduction Engine is opt-in: an absent `reduction` mapping or
`enabled: false` uses the unchanged legacy routing path.

> **Scope notice:** Reduction Engine v1 also implements hierarchical,
> collection, semantic, structured-relational, nested execution, production
> hardening, and retention contracts. See the consolidated
> [Reduction Engine v1 guide](reduction_engine_v1.md). The single-pass schema
> documented here still does not accept hierarchical-only options.

## Text concatenation

```yaml
reduction:
  enabled: true
  controller: single_pass
  profile: concat_text
```

## JSON list concatenation

This profile keeps dictionaries and first-level dictionary list members in
stable slice order. It does not recursively flatten nested lists.

```yaml
reduction:
  enabled: true
  controller: single_pass
  profile: concat_json_list
```

## Legacy-compatible JSON deep merge

```yaml
reduction:
  enabled: true
  controller: single_pass
  profile: legacy_json_deep_merge
  options:
    conflict_policy: prefer_left
    dedup_lists: true
```

The supported deep-merge options are `conflict_policy`, `dedup_lists`,
`audit_enabled`, and `max_audit_samples`. Supported conflict policies are
`prefer_left`, `prefer_right`, `longer_str`, and `non_empty`.

## Mutual exclusion with legacy slice merging

Explicit Reduction Engine routing and legacy `merge_slices` routing cannot be
enabled together. The following configuration is invalid and fails validation:

```yaml
merge_slices: true

reduction:
  enabled: true
  profile: legacy_json_deep_merge
```

This file intentionally illustrates the original three single-pass profiles.
It is not an exhaustive list of v1 reducers. Hierarchical controllers and
their round/runtime options remain outside the **single-pass** configuration
shown here; use the consolidated guide for their current contracts.
