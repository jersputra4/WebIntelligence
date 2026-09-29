"""Map raw EnsembleData payloads to the provider-agnostic AccountResult schema.

Field names follow the payloads EnsembleData relays from each platform
(Twitter GraphQL "legacy" object, TikTok user/stats, Instagram web profile).
Every accessor is defensive: missing or oddly-typed fields become ``None``
instead of raising, and a payload without a recognizable user raises
``ProviderMalformedResponse``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.errors import ProviderMalformedResponse
from app.schemas.search import AccountResult


def _get(obj: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _url(value: Any) -> str | None:
    text = _str(value)
    if text and text.startswith(("https://", "http://")):
        return text
    return None


def _iso_from_twitter(value: Any) -> str | None:
    # e.g. "Tue Jun 02 20:12:29 +0000 2009"
    text = _str(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y").astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _iso_from_epoch(value: Any) -> str | None:
    seconds = _int(value)
    if not seconds:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def normalize_twitter(payload: Any, requested: str) -> AccountResult | None:
    data = _unwrap(payload)
    if data in (None, {}, []):
        return None
    if not isinstance(data, dict):
        raise ProviderMalformedResponse()
    # Accept either the GraphQL user result or a flat legacy object.
    user = _first(_get(data, "user", "result"), _get(data, "result"), data)
    legacy = _get(user, "legacy") if isinstance(_get(user, "legacy"), dict) else user
    if not isinstance(legacy, dict):
        raise ProviderMalformedResponse()
    screen_name = _str(_first(legacy.get("screen_name"), _get(user, "core", "screen_name")))
    if not screen_name and not legacy.get("name"):
        raise ProviderMalformedResponse()
    username = screen_name or requested
    avatar = _url(_first(legacy.get("profile_image_url_https"), _get(user, "avatar", "image_url")))
    if avatar:
        avatar = avatar.replace("_normal.", "_400x400.")
    urls = _get(legacy, "entities", "url", "urls")
    external_url = None
    if isinstance(urls, list) and urls and isinstance(urls[0], dict):
        external_url = _url(urls[0].get("expanded_url"))
    return AccountResult(
        platform="twitter",
        username=username,
        display_name=_str(_first(legacy.get("name"), _get(user, "core", "name"))),
        user_id=_str(_first(_get(user, "rest_id"), legacy.get("id_str"))),
        profile_url=f"https://x.com/{username}",
        avatar=avatar,
        bio=_str(legacy.get("description")),
        location=_str(_first(legacy.get("location"), _get(user, "location", "location"))),
        external_url=external_url,
        verified=bool(_first(_get(user, "is_blue_verified"), legacy.get("verified"), False)),
        private=bool(legacy.get("protected")) if legacy.get("protected") is not None else None,
        followers=_int(_first(legacy.get("followers_count"), legacy.get("normal_followers_count"))),
        following=_int(legacy.get("friends_count")),
        posts=_int(legacy.get("statuses_count")),
        likes=_int(legacy.get("favourites_count")),
        created_at=_iso_from_twitter(_first(legacy.get("created_at"), _get(user, "core", "created_at"))),
    )


def normalize_tiktok(payload: Any, requested: str) -> AccountResult | None:
    data = _unwrap(payload)
    if data in (None, {}, []):
        return None
    if not isinstance(data, dict):
        raise ProviderMalformedResponse()
    user = _first(_get(data, "user"), _get(data, "userInfo", "user"))
    stats = _first(_get(data, "stats"), _get(data, "userInfo", "stats"), {})
    if not isinstance(user, dict):
        raise ProviderMalformedResponse()
    username = _str(_first(user.get("uniqueId"), user.get("unique_id"))) or requested
    avatar = _url(_first(user.get("avatarLarger"), user.get("avatarMedium"), user.get("avatarThumb")))
    for key in ("avatar_larger", "avatar_medium"):
        urls = _get(user, key, "url_list")
        if avatar is None and isinstance(urls, list) and urls:
            avatar = _url(urls[0])
    return AccountResult(
        platform="tiktok",
        username=username,
        display_name=_str(user.get("nickname")),
        user_id=_str(_first(user.get("id"), user.get("uid"))),
        profile_url=f"https://www.tiktok.com/@{username}",
        avatar=avatar,
        bio=_str(user.get("signature")),
        external_url=_url(_get(user, "bioLink", "link")),
        verified=bool(user.get("verified", False)),
        private=user.get("privateAccount") if isinstance(user.get("privateAccount"), bool) else None,
        followers=_int(_first(_get(stats, "followerCount"), user.get("follower_count"))),
        following=_int(_first(_get(stats, "followingCount"), user.get("following_count"))),
        posts=_int(_first(_get(stats, "videoCount"), user.get("aweme_count"))),
        likes=_int(_first(_get(stats, "heartCount"), _get(stats, "heart"), user.get("total_favorited"))),
        created_at=_iso_from_epoch(_first(user.get("createTime"), user.get("create_time"))),
    )


def normalize_instagram(payload: Any, requested: str) -> AccountResult | None:
    data = _unwrap(payload)
    if data in (None, {}, []):
        return None
    if not isinstance(data, dict):
        raise ProviderMalformedResponse()
    user = _first(_get(data, "user"), data)
    if not isinstance(user, dict) or not (user.get("username") or user.get("pk") or user.get("id")):
        raise ProviderMalformedResponse()
    username = _str(user.get("username")) or requested
    return AccountResult(
        platform="instagram",
        username=username,
        display_name=_str(user.get("full_name")),
        user_id=_str(_first(user.get("pk"), user.get("id"))),
        profile_url=f"https://www.instagram.com/{username}/",
        avatar=_url(_first(user.get("profile_pic_url_hd"), _get(user, "hd_profile_pic_url_info", "url"), user.get("profile_pic_url"))),
        bio=_str(user.get("biography")),
        location=_str(user.get("city_name")),
        external_url=_url(user.get("external_url")),
        verified=bool(user.get("is_verified", False)),
        private=user.get("is_private") if isinstance(user.get("is_private"), bool) else None,
        followers=_int(_first(user.get("follower_count"), _get(user, "edge_followed_by", "count"))),
        following=_int(_first(user.get("following_count"), _get(user, "edge_follow", "count"))),
        posts=_int(_first(user.get("media_count"), _get(user, "edge_owner_to_timeline_media", "count"))),
    )


NORMALIZERS = {
    "twitter": normalize_twitter,
    "tiktok": normalize_tiktok,
    "instagram": normalize_instagram,
}


def normalize(platform: str, payload: Any, requested: str) -> AccountResult | None:
    return NORMALIZERS[platform](payload, requested)
