import logging
import random
import time
from typing import Any

import httpx

from app.config import Settings
from app.keitaro.base import KeitaroError

logger = logging.getLogger(__name__)


class HttpKeitaroClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.Client(
            base_url=f"{settings.keitaro_base_url}/admin_api/v1",
            headers={
                "Api-Key": settings.keitaro_api_key.get_secret_value(),
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(settings.keitaro_timeout_seconds),
        )

    def _request(
        self, method: str, path: str, *, json: dict[str, Any] | None = None
    ) -> Any:
        retries = self.settings.keitaro_get_retries if method == "GET" else 0
        for attempt in range(retries + 1):
            started = time.monotonic()
            try:
                response = self._client.request(method, path, json=json)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < retries:
                    time.sleep(0.15 * (2**attempt) + random.random() * 0.05)
                    continue
                response.raise_for_status()
                logger.info(
                    "keitaro_request method=%s path=%s status=%s duration_ms=%s",
                    method,
                    path,
                    response.status_code,
                    round((time.monotonic() - started) * 1000),
                )
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt < retries:
                    time.sleep(0.15 * (2**attempt) + random.random() * 0.05)
                    continue
                raise KeitaroError(
                    "upstream_timeout",
                    "Keitaro did not respond in time",
                    retryable=method == "GET",
                    outcome_unknown=method != "GET",
                ) from exc
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 401:
                    code, message = "upstream_unauthorized", "Keitaro rejected the API key"
                elif status == 404:
                    code, message = "upstream_not_found", "Keitaro resource was not found"
                elif status == 402:
                    code = "upstream_unavailable"
                    message = "Admin API is unavailable in this edition"
                else:
                    code, message = "upstream_rejected", f"Keitaro rejected the request ({status})"
                raise KeitaroError(code, message, retryable=status >= 500) from exc
        raise AssertionError("unreachable")

    def list_offers(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "/offers"))

    def get_campaign(self, campaign_id: int) -> dict[str, Any]:
        return dict(self._request("GET", f"/campaigns/{campaign_id}"))

    def create_campaign(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(self._request("POST", "/campaigns", json=payload))

    def get_streams(self, campaign_id: int) -> list[dict[str, Any]]:
        return list(self._request("GET", f"/campaigns/{campaign_id}/streams"))

    def create_stream(self, campaign_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(self._request("POST", f"/campaigns/{campaign_id}/streams", json=payload))

    def update_stream(self, stream_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(self._request("PUT", f"/streams/{stream_id}", json=payload))
