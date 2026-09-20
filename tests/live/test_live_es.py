import pytest


@pytest.mark.live_es
def test_live_es_owned_document_round_trip(live_es_config, live_run_id):
    from elasticsearch import Elasticsearch

    kwargs = {}
    # Credentials are optional and are never logged by the test.
    import os
    if os.getenv("LIVE_ES_USER") and os.getenv("LIVE_ES_PASS"):
        kwargs["http_auth"] = (os.environ["LIVE_ES_USER"], os.environ["LIVE_ES_PASS"])
    client = Elasticsearch([live_es_config["LIVE_ES_URL"]], **kwargs)
    source = live_es_config["LIVE_ES_SOURCE_INDEX"]
    target = live_es_config["LIVE_ES_TARGET_INDEX"]
    try:
        client.index(index=source, id=live_run_id, body={"rawInfo": {"content": "live ES input"}}, refresh=True)
        client.index(index=target, id=live_run_id, body={"analysis": "RESULT::" + live_run_id}, refresh=True)
        assert client.get(index=target, id=live_run_id)["_source"]["analysis"] == "RESULT::" + live_run_id
    finally:
        for index in {source, target}:
            client.delete(index=index, id=live_run_id, ignore=[404], refresh=True)
