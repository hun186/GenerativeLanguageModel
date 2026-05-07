from czjLLM.es_mode.adapters.elasticsearch_adapter import ElasticsearchAdapter


def test_build_personal_filters_combines_note_stock_and_list_with_pending_filters():
    adapter = ElasticsearchAdapter(
        {
            "pending_filters": {"rawInfo.langCode.keyword": "zh"},
            "only_selected": True,
            "personal_filters": {
                "note_keywords": ["追蹤"],
                "stock_names": ["台積電"],
                "stock_codes": ["2330"],
                "list_filter": ["聯發科", "2454"],
                "note_fields": ["userNote"],
                "stock_name_fields": ["rawInfo.stockName"],
                "stock_code_fields": ["rawInfo.stockCode"],
            },
        }
    )

    filters = adapter._build_pending_filters()

    assert {"term": {"rawInfo.langCode.keyword": "zh"}} in filters
    assert {"term": {"selectedMessage": True}} in filters
    personal_filter = filters[-1]
    assert personal_filter["bool"]["minimum_should_match"] == 1

    rendered = str(personal_filter)
    assert "userNote" in rendered
    assert "rawInfo.stockName" in rendered
    assert "rawInfo.stockCode.keyword" in rendered
    assert "2330" in rendered
    assert "2454" in rendered


def test_top_level_stock_codes_are_supported_without_personal_filter_block():
    adapter = ElasticsearchAdapter(
        {
            "stock_codes": "AAPL, MSFT",
            "stock_code_fields": ["ticker"],
        }
    )

    filters = adapter._build_pending_filters()

    assert len(filters) == 1
    rendered = str(filters[0])
    assert "ticker.keyword" in rendered
    assert "AAPL" in rendered
    assert "MSFT" in rendered


def test_structured_list_filter_can_target_custom_fields():
    adapter = ElasticsearchAdapter(
        {
            "list_filter": {
                "field": "portfolio.symbol",
                "values": ["NVDA", "TSM"],
                "exact": True,
            }
        }
    )

    filters = adapter._build_pending_filters()

    assert len(filters) == 1
    rendered = str(filters[0])
    assert "portfolio.symbol.keyword" in rendered
    assert "NVDA" in rendered
    assert "TSM" in rendered
