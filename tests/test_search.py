"""API behaviour tests: validation, rate limiting, history, status, security."""
import httpx
import pytest

from conftest import TEST_KEY
from test_ensembledata import TWITTER_PAYLOAD


def ok_handler(request):
    return httpx.Response(200, json=TWITTER_PAYLOAD)


def test_health(make_client):
    assert make_client().get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("params,code", [
    ({}, "USERNAME_REQUIRED"),
    ({"username": "   "}, "USERNAME_REQUIRED"),
    ({"username": "bad name!"}, "INVALID_USERNAME"),
    ({"username": "x" * 31}, "INVALID_USERNAME"),
    ({"username": "<script>"}, "INVALID_USERNAME"),
])
def test_invalid_usernames_return_400(make_client, params, code):
    res = make_client(ok_handler).get("/api/search", params=params)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == code


def test_invalid_platform_returns_400(make_client):
    res = make_client(ok_handler).get("/api/search", params={"username": "a", "platform": "myspace"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_REQUEST"


def test_rate_limit_per_ip(make_client):
    client = make_client(ok_handler, rate_limit_requests=2)
    assert client.get("/api/search", params={"username": "a"}).status_code == 200
    assert client.get("/api/search", params={"username": "a"}).status_code == 200
    res = client.get("/api/search", params={"username": "a"})
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "RATE_LIMITED"
    assert int(res.headers["Retry-After"]) >= 1


def test_history_trend_and_status(make_client):
    client = make_client(ok_handler)
    client.get("/api/search", params={"username": "example"})
    client.get("/api/search", params={"username": "example"})
    client.get("/api/search", params={"username": "bad name"})  # validation errors are not logged

    history = client.get("/api/history").json()
    assert history["total"] == 2
    item = history["items"][0]
    assert item["username"] == "example" and item["status"] == "success"
    assert item["display_name"] == "Example Person"

    trend = client.get("/api/accounts/twitter/example/trend").json()
    assert len(trend["points"]) == 2 and trend["points"][0]["followers"] == 1234567

    status = client.get("/api/system/status").json()
    assert status["inquiries"]["today"] == 2
    assert status["provider"]["api_key_configured"] is True
    assert TEST_KEY not in str(status)

    assert client.delete("/api/history").json()["deleted"] == 2
    assert client.get("/api/history").json()["total"] == 0


def test_failed_search_is_logged(make_client):
    client = make_client(lambda r: httpx.Response(401, json={}))
    client.get("/api/search", params={"username": "someone"})
    item = client.get("/api/history").json()["items"][0]
    assert item["status"] == "error" and item["error_code"] == "PROVIDER_UNAUTHORIZED"


def test_demo_mode_returns_labelled_synthetic_data(make_client):
    client = make_client(ensembledata_api_key="", provider_mode_setting="auto")
    res = client.get("/api/search", params={"username": "anyone", "platform": "instagram"})
    result = res.json()["results"][0]
    assert result["source"] == "demo"
    assert res.json()["meta"]["mode"] == "mock"
    assert client.get("/api/search", params={"username": "notfound_user"}).json()["results"] == []


def test_avatar_proxy_rejects_unknown_hosts(make_client):
    client = make_client()
    for url in ["https://evil.example.com/a.jpg", "http://pbs.twimg.com/a.jpg", "https://twimg.com.evil.io/x"]:
        res = client.get("/api/avatar", params={"url": url})
        assert res.status_code == 400


def test_security_headers_and_frontend(make_client):
    client = make_client()
    res = client.get("/")
    assert res.status_code == 200
    assert "Specter Intel" in res.text
    assert "default-src 'self'" in res.headers["Content-Security-Policy"]
    assert res.headers["X-Content-Type-Options"] == "nosniff"


def test_api_key_not_in_frontend_assets(make_client):
    client = make_client()
    for path in ["/", "/app.js", "/style.css"]:
        assert TEST_KEY not in client.get(path).text
