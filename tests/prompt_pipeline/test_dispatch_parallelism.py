from types import SimpleNamespace

from czjLLM.prompt_pipeline.dispatch_parallelism import (
    configured_model_process_parallelism,
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
