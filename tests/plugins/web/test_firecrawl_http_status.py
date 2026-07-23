"""Regression tests for Firecrawl upstream HTTP error handling."""

from __future__ import annotations

import asyncio

import pytest

from plugins.web.firecrawl import provider as firecrawl_provider


class _FakeFirecrawlClient:
    def __init__(self, status_code: int, *, snake_case: bool = False) -> None:
        self.status_code = status_code
        self.snake_case = snake_case

    def scrape(self, **_kwargs):
        metadata = {
            "title": f"{self.status_code} upstream response",
            "status_code" if self.snake_case else "statusCode": self.status_code,
            "source_url" if self.snake_case else "sourceURL": (
                "https://example.com/unavailable"
            ),
        }
        return {
            "success": True,
            "data": {
                "markdown": "Service Temporarily Unavailable",
                "metadata": metadata,
            },
        }


@pytest.mark.parametrize("status_code", [404, 503])
@pytest.mark.parametrize("snake_case", [False, True], ids=["gateway", "sdk"])
def test_extract_surfaces_upstream_http_errors(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    snake_case: bool,
) -> None:
    """A successful Firecrawl envelope must not hide a failed page fetch."""
    monkeypatch.setattr(
        firecrawl_provider,
        "_get_firecrawl_client",
        lambda: _FakeFirecrawlClient(status_code, snake_case=snake_case),
    )
    monkeypatch.setattr(firecrawl_provider, "check_website_access", lambda _url: None)
    monkeypatch.setattr(firecrawl_provider, "is_safe_url", lambda _url: True)

    result = asyncio.run(
        firecrawl_provider.FirecrawlWebSearchProvider().extract(
            ["https://example.com/unavailable"],
            format="markdown",
        )
    )

    assert result[0]["url"] == "https://example.com/unavailable"
    assert result[0]["title"] == f"{status_code} upstream response"
    assert result[0]["content"] == ""
    assert result[0]["raw_content"] == ""
    assert result[0]["error"] == f"Upstream server returned HTTP {status_code}"
    assert result[0]["metadata"][
        "status_code" if snake_case else "statusCode"
    ] == status_code


@pytest.mark.parametrize("snake_case", [False, True], ids=["gateway", "sdk"])
def test_extract_keeps_successful_http_response(
    monkeypatch: pytest.MonkeyPatch,
    snake_case: bool,
) -> None:
    """The status check must not change successful extraction results."""
    monkeypatch.setattr(
        firecrawl_provider,
        "_get_firecrawl_client",
        lambda: _FakeFirecrawlClient(200, snake_case=snake_case),
    )
    monkeypatch.setattr(firecrawl_provider, "check_website_access", lambda _url: None)
    monkeypatch.setattr(firecrawl_provider, "is_safe_url", lambda _url: True)

    result = asyncio.run(
        firecrawl_provider.FirecrawlWebSearchProvider().extract(
            ["https://example.com/unavailable"],
            format="markdown",
        )
    )

    assert "error" not in result[0]
    assert result[0]["content"] == "Service Temporarily Unavailable"


def test_extract_ignores_generic_metadata_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Page-controlled document metadata must not replace the extraction URL."""

    class _GenericMetadataUrlClient:
        def scrape(self, **_kwargs):
            return {
                "success": True,
                "data": {
                    "markdown": "Expected content",
                    "metadata": {
                        "title": "Expected title",
                        "statusCode": 200,
                        "url": "https://attacker.example/spoofed",
                    },
                },
            }

    checked_urls: list[str] = []
    monkeypatch.setattr(
        firecrawl_provider,
        "_get_firecrawl_client",
        lambda: _GenericMetadataUrlClient(),
    )
    monkeypatch.setattr(
        firecrawl_provider,
        "check_website_access",
        lambda checked_url: checked_urls.append(checked_url),
    )
    monkeypatch.setattr(firecrawl_provider, "is_safe_url", lambda _url: True)

    requested_url = "https://example.com/article"
    result = asyncio.run(
        firecrawl_provider.FirecrawlWebSearchProvider().extract(
            [requested_url],
            format="markdown",
        )
    )

    assert result[0]["url"] == requested_url
    assert result[0]["content"] == "Expected content"
    assert checked_urls == [requested_url, requested_url]
