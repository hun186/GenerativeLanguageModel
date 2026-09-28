from types import SimpleNamespace

import pytest

from czjLLM.prompt_pipeline.dispatch_parallelism import (
    attach_execution_budget,
    cap_orchestration_workers,
    configured_model_process_parallelism,
    lease_execution_workers,
    resolve_execution_budget_capacity,
    resolve_slice_parallelism,
)


def test_slice_parallelism_defaults_to_existing_process_budget():
    ctx = SimpleNamespace(n_process=4)

    assert resolve_slice_parallelism(ctx, job_count=20) == 4


def test_multistage_slice_override_is_independent_of_row_parallelism():
    ctx = SimpleNamespace(
        n_process=2,
        multistage_row_parallelism=2,
        multistage_slice_parallelism=8,
    )

    assert resolve_slice_parallelism(ctx, job_count=20) == 8


def test_slice_parallelism_can_be_manually_overridden_in_model_profile():
    ctx = SimpleNamespace(
        n_process=4,
        model_spec={"slice_parallelism": 6},
    )

    assert resolve_slice_parallelism(ctx, job_count=20) == 6


def test_context_override_wins_over_model_profile():
    ctx = SimpleNamespace(
        n_process=4,
        multistage_slice_parallelism=3,
        model_spec={"slice_parallelism": 6},
    )

    assert resolve_slice_parallelism(ctx, job_count=20) == 3


def test_slice_parallelism_never_exceeds_available_jobs():
    ctx = SimpleNamespace(multistage_slice_parallelism=8, n_process=2)

    assert resolve_slice_parallelism(ctx, job_count=3) == 3


def test_invalid_override_falls_back_to_one_when_process_budget_is_invalid():
    ctx = SimpleNamespace(multistage_slice_parallelism="bad", n_process="bad")

    assert resolve_slice_parallelism(ctx, job_count=3) == 1


def test_model_process_parallelism_supports_existing_camel_case_key():
    assert configured_model_process_parallelism({"nProcess": 4}) == 4


def test_model_process_parallelism_prefers_canonical_snake_case_key():
    assert configured_model_process_parallelism({"n_process": 3, "nProcess": 4}) == 3


def test_model_process_parallelism_returns_zero_for_auto_mode():
    assert configured_model_process_parallelism({"nProcess": "invalid"}) == 0


def test_budget_default_uses_widest_local_and_model_desired_width():
    ctx = SimpleNamespace(
        n_process=2,
        multistage_row_parallelism=4,
        multistage_slice_parallelism=8,
        model_spec={"nProcess": 6, "slice_parallelism": 7},
    )

    assert resolve_execution_budget_capacity(ctx) == 8


def test_budget_model_process_aliases_and_slice_override_are_candidates():
    assert resolve_execution_budget_capacity(SimpleNamespace(model_spec={"n_process": 3})) == 3
    assert resolve_execution_budget_capacity(SimpleNamespace(model_spec={"nProcess": 4})) == 4
    assert resolve_execution_budget_capacity(SimpleNamespace(model_spec={"slice_parallelism": 5})) == 5


def test_budget_root_override_wins_over_model_override_and_derived_width():
    ctx = SimpleNamespace(
        execution_budget_capacity=4,
        n_process=2,
        slice_parallelism=8,
        model_spec={"execution_budget_capacity": 6},
    )

    assert resolve_execution_budget_capacity(ctx) == 4


def test_budget_model_override_wins_over_derived_width():
    ctx = SimpleNamespace(n_process=2, slice_parallelism=8, model_spec={"execution_budget_capacity": 5})
    assert resolve_execution_budget_capacity(ctx) == 5


def test_budget_capacity_falls_back_to_one():
    assert resolve_execution_budget_capacity(SimpleNamespace()) == 1


def test_bool_and_other_invalid_explicit_budget_values_are_rejected():
    for value in (True, 0, -1, "8"):
        with pytest.raises(ValueError, match="execution_budget_capacity"):
            resolve_execution_budget_capacity(SimpleNamespace(execution_budget_capacity=value))


def test_attached_budget_preserves_long_document_width_and_caps_combined_leases():
    ctx = SimpleNamespace(n_process=2, slice_parallelism=8)
    budget = attach_execution_budget(ctx)

    assert budget.capacity == 8
    with lease_execution_workers(ctx, resolve_slice_parallelism(ctx, 20)) as granted:
        assert granted == 8
    with lease_execution_workers(ctx, 6) as first:
        with lease_execution_workers(ctx, resolve_slice_parallelism(ctx, 20)) as second:
            assert first == 6
            assert second == 2
            assert first + second <= 8


def test_orchestration_cap_does_not_consume_leaf_permits():
    ctx = SimpleNamespace(n_process=4, execution_budget_capacity=4)
    budget = attach_execution_budget(ctx)

    assert cap_orchestration_workers(ctx, 9) == 4
    assert budget.snapshot().in_use == 0
    with lease_execution_workers(ctx, 4) as granted:
        assert granted == 4
