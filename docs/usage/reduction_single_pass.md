# Single-pass Reduction Engine configuration

PR C supports explicit, single-pass reduction at the existing combine boundary.
The Reduction Engine is opt-in: an absent `reduction` mapping or
`enabled: false` uses the unchanged legacy routing path.

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

PR C supports only `controller: single_pass` and the three profiles shown
above. Hierarchical controllers, repeated rounds, collection aggregation, and
semantic reduction are not part of this configuration contract.
