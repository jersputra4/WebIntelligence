"""Provider integration tests: HTTP error mapping, retry and normalization."""
import httpx
import pytest

from app.core.errors import ProviderMalformedResponse
from app.services.normalizer import normalize

from conftest import TEST_KEY

TWITTER_PAYLOAD = {
    "data": {
        "rest_id": "44196397",
        "is_blue_verified": True,
        "legacy": {
            "name": "Example Person",
            "screen_name": "example",
            "description": "Bio text",
            "location": "Somewhere",
            "followers_count": 1234567,
            "friends_count": 890,
            "statuses_count": 54200,
            "created_at": "Tue Jun 02 20:12:29 +0000 2009",
            "profile_image_url_https": "https://pbs.twimg.com/profile_images/1/a_normal.jpg",
        },
    }
}
TIKTOK_PAYLOAD = {
    "data": {
        "user": {"id": "1", "uniqueId": "tiktoker", "nickname": "Tik Toker", "signature": "hi",
                 "verified": False, "avatarLarger": "https://p16.tiktokcdn.com/a.jpg", "createTime": 1500000000},
        "stats": {"followerCount": 10, "followingCount": 2, "videoCount": 3, "heartCount": 99},
    }
}
INSTAGRAM_PAYLOAD = {
    "data": {"pk": "42", "username": "insta", "full_name": "Insta Gram", "biography": "bio",
             "is_verified": True, "is_private": False, "follower_count": 500, "following_count": 5,
             "media_count": 7, "profile_pic_url_hd": "https://scontent.cdninstagram.com/p.jpg"}
}


def test_twitter_request_and_normalization(make_client):
    seen = {}

    def handler(request: httpx.Request):
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=TWITTER_PAYLOAD)

    client = make_client(handler)
    res = client.get("/api/search", params={"username": "@example", "platform": "twitter"})
    assert res.status_code == 200
    body = res.json()
    assert seen["path"] == "/apis/twitter/user/info"
    assert seen["params"] == {"name": "example", "token": TEST_KEY}
    result = body["results"][0]
    assert result["display_name"] == "Example Person"
    assert result["followers"] == 1234567
    assert result["verified"] is True
    assert result["created_at"].startswith("2009-06-02")
    assert result["avatar"].endswith("a_400x400.jpg")
    assert result["profile_url"] == "https://x.com/example"
    # The API key must never be echoed back to the browser.
    assert TEST_KEY not in res.text


def test_tiktok_and_instagram_normalization():
    tt = normalize("tiktok", TIKTOK_PAYLOAD, "tiktoker")
    assert (tt.username, tt.followers, tt.posts, tt.likes) == ("tiktoker", 10, 3, 99)
    assert tt.created_at.startswith("2017-07-14")
    ig = normalize("instagram", INSTAGRAM_PAYLOAD, "insta")
    assert (ig.display_name, ig.followers, ig.following, ig.posts, ig.verified) == ("Insta Gram", 500, 5, 7, True)


@pytest.mark.parametrize("payload", [{"data": "oops"}, {"data": {"unexpected": 1}}, ["x"]])
def test_malformed_payload_raises(payload):
    with pytest.raises(ProviderMalformedResponse):
        normalize("instagram", payload, "x")


@pytest.mark.parametrize(
    "status,body,expected_status,expected_code",
    [
        (401, {"detail": "invalid token"}, 502, "PROVIDER_UNAUTHORIZED"),
        (429, {"detail": "slow down"}, 429, "PROVIDER_RATE_LIMITED"),
        (495, {"detail": "units exceeded"}, 429, "PROVIDER_RATE_LIMITED"),
        (500, {"detail": "boom"}, 502, "PROVIDER_UNAVAILABLE"),
        (418, {"detail": "teapot"}, 502, "PROVIDER_ERROR"),
    ],
)
def test_provider_http_errors(make_client, status, body, expected_status, expected_code):
    client = make_client(lambda request: httpx.Response(status, json=body))
    res = client.get("/api/search", params={"username": "someone"})
    assert res.status_code == expected_status
    assert res.json() == {"success": False, "error": {"code": expected_code, "message": res.json()["error"]["message"]}}
    assert TEST_KEY not in res.text


def test_provider_timeout_maps_to_504(make_client):
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    res = make_client(handler).get("/api/search", params={"username": "someone"})
    assert res.status_code == 504
    assert res.json()["error"]["code"] == "PROVIDER_TIMEOUT"


def test_retry_on_server_error_then_success(make_client):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"detail": "busy"})
        return httpx.Response(200, json=TWITTER_PAYLOAD)

    res = make_client(handler, request_retries=1).get("/api/search", params={"username": "example"})
    assert res.status_code == 200
    assert calls["n"] == 2


def test_malformed_json_maps_to_502(make_client):
    client = make_client(lambda request: httpx.Response(200, content=b"<html>not json</html>"))
    res = client.get("/api/search", params={"username": "someone"})
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "PROVIDER_MALFORMED_RESPONSE"


def test_not_found_returns_empty_results(make_client):
    client = make_client(lambda request: httpx.Response(404, json={"detail": "User not found"}))
    res = client.get("/api/search", params={"username": "ghost"})
    assert res.status_code == 200
    assert res.json()["results"] == []


def test_multiple_results_across_platforms(make_client):
    def handler(request):
        path = request.url.path
        if path.endswith("/twitter/user/info"):
            return httpx.Response(200, json=TWITTER_PAYLOAD)
        if path.endswith("/tt/user/info"):
            return httpx.Response(200, json=TIKTOK_PAYLOAD)
        return httpx.Response(500, json={"detail": "down"})

    res = make_client(handler).get("/api/search", params={"username": "example", "platform": "all"})
    assert res.status_code == 200
    body = res.json()
    assert sorted(r["platform"] for r in body["results"]) == ["tiktok", "twitter"]
    assert body["warnings"] == [{"platform": "instagram", "code": "PROVIDER_UNAVAILABLE",
                                 "message": "External data provider is unavailable"}]


def test_live_mode_without_key_is_reported(make_client):
    client = make_client(ensembledata_api_key="")
    res = client.get("/api/search", params={"username": "someone"})
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "PROVIDER_NOT_CONFIGURED"
