from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.keitaro.base import KeitaroError
from app.keitaro.http import HttpKeitaroClient


def make_client(
    handler: Callable[[httpx.Request], httpx.Response], *, retries: int = 0
) -> HttpKeitaroClient:
    settings = Settings(
        keitaro_mode="http",
        keitaro_api_key="test-secret",
        keitaro_get_retries=retries,
        keitaro_timeout_seconds=0.1,
    )
    return HttpKeitaroClient(settings, transport=httpx.MockTransport(handler))


def test_get_sends_api_key_and_returns_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Api-Key"] == "test-secret"
        assert request.url.path == "/admin_api/v1/offers"
        return httpx.Response(200, json=[{"id": 1, "name": "Offer", "state": "active"}])

    assert make_client(handler).list_offers()[0]["id"] == 1


def test_get_retries_transient_status(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    monkeypatch.setattr(HttpKeitaroClient, "_sleep", staticmethod(lambda _attempt: None))

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json=[])

    assert make_client(handler, retries=2).list_offers() == []
    assert attempts == 3


def test_mutation_5xx_is_not_retried_and_outcome_is_unknown() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"error": "busy"})

    with pytest.raises(KeitaroError) as caught:
        make_client(handler, retries=3).create_campaign({"name": "A"})

    assert attempts == 1
    assert caught.value.code == "upstream_unavailable"
    assert caught.value.outcome_unknown is True
    assert caught.value.retryable is False


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "upstream_unauthorized", False),
        (402, "upstream_unavailable", False),
        (404, "upstream_not_found", False),
        (408, "upstream_timeout", True),
        (429, "upstream_rate_limited", True),
        (500, "upstream_unavailable", True),
    ],
)
def test_get_status_mapping(status: int, code: str, retryable: bool) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "no"})

    with pytest.raises(KeitaroError) as caught:
        make_client(handler).list_offers()

    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert caught.value.outcome_unknown is False


@pytest.mark.parametrize(
    "error_type",
    [httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError],
)
def test_get_retries_timeout_and_network(
    error_type: type[httpx.RequestError], monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0
    monkeypatch.setattr(HttpKeitaroClient, "_sleep", staticmethod(lambda _attempt: None))

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise error_type("network failure", request=request)

    with pytest.raises(KeitaroError) as caught:
        make_client(handler, retries=2).list_offers()

    assert attempts == 3
    assert caught.value.code == "upstream_timeout"
    assert caught.value.retryable is True
    assert caught.value.outcome_unknown is False


def test_mutation_network_error_is_not_retried() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("lost response", request=request)

    with pytest.raises(KeitaroError) as caught:
        make_client(handler, retries=4).update_stream(10, {"offers": []})

    assert attempts == 1
    assert caught.value.outcome_unknown is True
    assert caught.value.retryable is False


def test_non_json_success_is_stable_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    with pytest.raises(KeitaroError) as caught:
        make_client(handler).list_offers()

    assert caught.value.code == "upstream_invalid_response"
    assert caught.value.outcome_unknown is False


@pytest.mark.parametrize(
    ("operation", "payload", "outcome_unknown"),
    [
        ("offers", {"items": []}, False),
        ("campaign", [], True),
    ],
)
def test_unexpected_success_shape(
    operation: str, payload: Any, outcome_unknown: bool
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = make_client(handler)
    with pytest.raises(KeitaroError) as caught:
        if operation == "offers":
            client.list_offers()
        else:
            client.create_campaign({"name": "A"})

    assert caught.value.code == "upstream_invalid_response"
    assert caught.value.outcome_unknown is outcome_unknown
