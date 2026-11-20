import logging
import random
import time
from typing import Any, ClassVar

import httpx

from app.config import Settings
from app.keitaro.base import KeitaroError

logger = logging.getLogger(__name__)


class HttpKeitaroClient:
    _TRANSIENT_STATUSES: ClassVar[frozenset[int]] = frozenset(
        {408, 429, 500, 502, 503, 504}
    )
    _MUTATING_METHODS: ClassVar[frozenset[str]] = frozenset(
        {"POST", "PUT", "PATCH", "DELETE"}
    )

    def __init__(
        self, settings: Settings, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.settings = settings
        self._client = httpx.Client(
            base_url=f"{settings.keitaro_base_url}/admin_api/v1",
            headers={
                "Api-Key": settings.keitaro_api_key.get_secret_value(),
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(settings.keitaro_timeout_seconds),
            transport=transport,
        )

    @staticmethod
    def _sleep(attempt: int) -> None:
        time.sleep(0.15 * (2**attempt) + random.random() * 0.05)

    @classmethod
    def _status_error(cls, method: str, status: int) -> KeitaroError:
        mutating = method in cls._MUTATING_METHODS
        outcome_unknown = mutating and (status >= 500 or status == 408)
        if status == 401:
            code, message = "upstream_unauthorized", "Keitaro rejected the API key"
        elif status == 402:
            code, message = "upstream_unavailable", "Admin API is unavailable in this edition"
        elif status == 404:
            code, message = "upstream_not_found", "Keitaro resource was not found"
        elif status == 408:
            code, message = "upstream_timeout", "Keitaro timed out while processing the request"
        elif status == 429:
            code, message = "upstream_rate_limited", "Keitaro rate limit was reached"
        elif status >= 500:
            code, message = "upstream_unavailable", f"Keitaro returned a server error ({status})"
        else:
            code, message = "upstream_rejected", f"Keitaro rejected the request ({status})"
        return KeitaroError(
            code,
            message,
            retryable=not mutating and status in cls._TRANSIENT_STATUSES,
            outcome_unknown=outcome_unknown,
        )

    @staticmethod
    def _invalid_response(*, mutating: bool) -> KeitaroError:
        return KeitaroError(
            "upstream_invalid_response",
            "Keitaro returned an unexpected response",
            retryable=not mutating,
            outcome_unknown=mutating,
        )

    def _request(
        self, method: str, path: str, *, json: dict[str, Any] | None = None
    ) -> Any:
        method = method.upper()
        retries = self.settings.keitaro_get_retries if method == "GET" else 0
        for attempt in range(retries + 1):
            started = time.monotonic()
            try:
                response = self._client.request(method, path, json=json)
                if (
                    response.status_code in self._TRANSIENT_STATUSES
                    and attempt < retries
                ):
                    self._sleep(attempt)
                    continue
                if response.is_error:
                    raise self._status_error(method, response.status_code)
                logger.info(
                    "keitaro_request method=%s path=%s status=%s duration_ms=%s",
                    method,
                    path,
                    response.status_code,
                    round((time.monotonic() - started) * 1000),
                )
                try:
                    return response.json()
                except ValueError as exc:
                    if attempt < retries:
                        self._sleep(attempt)
                        continue
                    raise self._invalid_response(
                        mutating=method in self._MUTATING_METHODS
                    ) from exc
            except httpx.TransportError as exc:
                if attempt < retries:
                    self._sleep(attempt)
                    continue
                raise KeitaroError(
                    "upstream_timeout",
                    "Keitaro did not respond in time",
                    retryable=method == "GET",
                    outcome_unknown=method != "GET",
                ) from exc
            except KeitaroError:
                raise
        raise AssertionError("unreachable")

    @staticmethod
    def _as_list(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise HttpKeitaroClient._invalid_response(mutating=False)
        return value

    @staticmethod
    def _as_dict(value: Any, *, mutating: bool) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise HttpKeitaroClient._invalid_response(mutating=mutating)
        return value

    def list_offers(self) -> list[dict[str, Any]]:
        return self._as_list(self._request("GET", "/offers"))

    def get_campaign(self, campaign_id: int) -> dict[str, Any]:
        return self._as_dict(
            self._request("GET", f"/campaigns/{campaign_id}"), mutating=False
        )

    def create_campaign(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._as_dict(
            self._request("POST", "/campaigns", json=payload), mutating=True
        )

    def get_streams(self, campaign_id: int) -> list[dict[str, Any]]:
        return self._as_list(
            self._request("GET", f"/campaigns/{campaign_id}/streams")
        )

    def create_stream(self, campaign_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._as_dict(
            self._request(
                "POST", "/streams", json={"campaign_id": campaign_id, **payload}
            ),
            mutating=True,
        )

    def update_stream(self, stream_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._as_dict(
            self._request("PUT", f"/streams/{stream_id}", json=payload),
            mutating=True,
        )
