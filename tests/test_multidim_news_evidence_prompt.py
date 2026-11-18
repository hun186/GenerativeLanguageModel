"""Offline source-only guard and operator A/B fixtures for Issue #337.

This does NOT run an LLM, validate generated JSON, or establish production quality.
"""

import ast
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "czjLLM/task_configs/taskSetting_Enrichment.py"
CASES = ROOT / "tests/fixtures/news_evidence_prompt_cases.json"


def _active_rule():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    definitions = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "MULTIDIM_EXTRACTION_Rule"
                for t in node.targets)
    ]
    assert len(definitions) == 1
    rule = ast.literal_eval(definitions[0].value)
    assert isinstance(rule, str)
    return rule


def test_general_news_preference_is_mode_scoped_and_source_faithful():
    rule = _active_rule()
    news_start = rule.index("【一般新聞模式 evidence 規則】")
    news_end = rule.index("【輸出結構】", news_start)
    news = rule[news_start:news_end]
    prior_modes = rule[rule.index("【逐條收錄模式（最高優先硬性規則）】"):news_start]
    assert "主體＋具體行動／狀態＋必要對象／結果" in news
    assert "不得拼接不同句子、不同 Event" in news
    assert "不得為符合此選句偏好而臆造、改寫或刪除合法短證據" in news
    assert "不能僅以日期存在作為主要事件證據優先條件" in news
    assert "主體＋具體行動／狀態＋必要對象／結果" not in prior_modes
    assert "每一筆 evidence_snippets.text 必須直接從輸入原文逐字擷取" in news
    assert "單一片段最長不超過 280 字" in news
    assert "event_ids" in news
    assert rule.index("【結構化紀錄模式規則】") < news_start
    assert rule.index("【逐條收錄模式（最高優先硬性規則）】") < news_start


def test_both_active_multidim_tasks_use_same_rule_not_duplicate_copy():
    src = SOURCE.read_text(encoding="utf-8")
    assert src.count('f"{MULTIDIM_EXTRACTION_Rule}"') == 2
    assert '"InfoExtraction-MultiDim-SQLFriendly-to json format"' in src
    assert '"InfoExtraction-MultiDim-Compact-SQLFriendly-to json format"' in src


def test_synthetic_cases_are_valid_source_quotes_not_model_outputs():
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    assert {c["case_id"] for c in cases} == {
        "news_action_over_date", "only_date_no_action",
        "two_distinct_events", "event_date_empty_timeline",
        "structured_record_unchanged", "news_280_boundary",
    }
    for case in cases:
        source = case["source"]
        expected = case["expected_quotes"]
        assert source and expected and isinstance(case["expected_timeline"], list)
        assert case["mode"] in {"general_news", "structured_record"}
        for quote in expected:
            assert quote["text"] in source
            assert quote["event_ids"] == list(dict.fromkeys(quote["event_ids"]))
            if case["mode"] == "general_news":
                assert len(quote["text"]) <= 280
    multi = next(c for c in cases if c["case_id"] == "two_distinct_events")
    assert [q["event_ids"] for q in multi["expected_quotes"]] == [["E1"], ["E2"]]
    date_only = next(c for c in cases if c["case_id"] == "only_date_no_action")
    assert date_only["expected_quotes"][0]["event_ids"] == []
    long_news = next(c for c in cases if c["case_id"] == "news_280_boundary")
    assert len(long_news["source"]) > 280


@pytest.mark.parametrize("case_id", [
    "news_action_over_date", "only_date_no_action", "two_distinct_events",
    "event_date_empty_timeline", "structured_record_unchanged",
    "news_280_boundary",
])
def test_fixture_ids_have_unique_named_cases(case_id):
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    assert sum(case["case_id"] == case_id for case in cases) == 1
