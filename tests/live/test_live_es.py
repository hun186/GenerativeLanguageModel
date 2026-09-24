import pytest


@pytest.mark.live_es
def test_live_es_service_owned_document_round_trip(live_es_config, live_run_id):
    """Connectivity/storage smoke only; offline E2E owns adapter/sink coverage."""
    from elasticsearch import Elasticsearch

    kwargs = {}
    # Credentials are optional and are never logged by the test.
    import os
    if os.getenv("LIVE_ES_USER") and os.getenv("LIVE_ES_PASS"):
        kwargs["http_auth"] = (os.environ["LIVE_ES_USER"], os.environ["LIVE_ES_PASS"])
    verify = os.getenv("LIVE_ES_VERIFY_CERTS")
    if verify is not None:
        kwargs["verify_certs"] = verify.strip().lower() in {"1", "true", "yes", "on"}
    if os.getenv("LIVE_ES_CA_CERTS"):
        kwargs["ca_certs"] = os.environ["LIVE_ES_CA_CERTS"]
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
