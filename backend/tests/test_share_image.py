import asyncio
from unittest.mock import patch

from fastapi import HTTPException

from app.main import _fetch_share_image, _validated_share_image_url


class _FakeResponse:
    def __init__(self, status_code, *, headers=None, content=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content


class _FakeClient:
    def __init__(self, responses, **_kwargs):
        self.responses = list(responses)
        self.urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, url, **_kwargs):
        self.urls.append(url)
        return self.responses.pop(0)


def test_share_image_url_is_restricted_to_known_https_poster_hosts():
    assert _validated_share_image_url("https://image.tmdb.org/t/p/w500/a.jpg")
    assert _validated_share_image_url("https://a.ltrbxd.com/resized/a.jpg")

    blocked = (
        "http://image.tmdb.org/a.jpg",
        "https://image.tmdb.org.evil.example/a.jpg",
        "https://user:pass@image.tmdb.org/a.jpg",
        "https://image.tmdb.org:8443/a.jpg",
        "https://127.0.0.1/a.jpg",
    )
    for url in blocked:
        try:
            _validated_share_image_url(url)
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError(f"unsafe URL accepted: {url}")


def test_share_image_fetch_accepts_a_small_supported_image():
    fake = _FakeClient([
        _FakeResponse(200, headers={"content-type": "image/jpeg"}, content=b"jpeg"),
    ])
    with patch("app.main.httpx.AsyncClient", return_value=fake):
        content, media_type = asyncio.run(
            _fetch_share_image("https://image.tmdb.org/t/p/w500/a.jpg")
        )
    assert content == b"jpeg"
    assert media_type == "image/jpeg"


def test_share_image_fetch_revalidates_redirect_destination():
    fake = _FakeClient([
        _FakeResponse(302, headers={"location": "https://127.0.0.1/private"}),
    ])
    with patch("app.main.httpx.AsyncClient", return_value=fake):
        try:
            asyncio.run(_fetch_share_image("https://letterboxd.com/poster/a"))
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("unsafe redirect accepted")
