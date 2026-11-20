from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from app.keitaro.base import KeitaroError


def _now() -> str:
    return datetime.now(UTC).isoformat()


class FakeKeitaroClient:
    """Deterministic, stateful fake used by the demo and tests."""

    def __init__(self) -> None:
        self.offers: list[dict[str, Any]] = [
            {"id": 101, "name": "Aurora Health — US", "state": "active"},
            {"id": 102, "name": "Bright Loan — CA", "state": "active"},
            {"id": 103, "name": "Cedar Mobile — GB", "state": "active"},
            {"id": 104, "name": "Delta Games — DE", "state": "active"},
            {"id": 105, "name": "Evergreen Home — ES", "state": "active"},
            {"id": 106, "name": "Fjord Fitness — NO", "state": "active"},
        ]
        self.campaigns: dict[int, dict[str, Any]] = {
            5001: {
                "id": 5001,
                "name": "Demo campaign",
                "alias": "demo-campaign",
                "domain_id": 1,
                "group_id": 1,
                "traffic_source_id": 1,
            }
        }
        self.streams: dict[int, list[dict[str, Any]]] = {
            5001: [
                {
                    "id": 6001,
                    "campaign_id": 5001,
                    "name": "US → Google",
                    "schema": "redirect",
                    "type": "regular",
                    "action_type": "http",
                    "action_payload": "https://www.google.com/",
                    "filters": [{"name": "country", "mode": "accept", "payload": ["US"]}],
                    "offers": [],
                    "updated_at": _now(),
                },
                {
                    "id": 6002,
                    "campaign_id": 5001,
                    "name": "Offers",
                    "schema": "landings",
                    "type": "default",
                    "action_type": "http",
                    "offers": [
                        {"offer_id": 101, "share": 34, "state": "active"},
                        {"offer_id": 102, "share": 33, "state": "active"},
                        {"offer_id": 103, "share": 33, "state": "active"},
                    ],
                    "updated_at": _now(),
                },
            ]
        }
        self._next_campaign_id = 5002
        self._next_stream_id = 6003
        self.fail_next_update = False

    def list_offers(self) -> list[dict[str, Any]]:
        return deepcopy(self.offers)

    def get_campaign(self, campaign_id: int) -> dict[str, Any]:
        try:
            return deepcopy(self.campaigns[campaign_id])
        except KeyError as exc:
            raise KeitaroError("upstream_not_found", "Campaign was not found") from exc

    def create_campaign(self, payload: dict[str, Any]) -> dict[str, Any]:
        campaign_id = self._next_campaign_id
        self._next_campaign_id += 1
        campaign = deepcopy(payload) | {"id": campaign_id}
        self.campaigns[campaign_id] = campaign
        self.streams[campaign_id] = []
        return deepcopy(campaign)

    def get_streams(self, campaign_id: int) -> list[dict[str, Any]]:
        if campaign_id not in self.campaigns:
            raise KeitaroError("upstream_not_found", "Campaign was not found")
        return deepcopy(self.streams[campaign_id])

    def create_stream(self, campaign_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        if campaign_id not in self.campaigns:
            raise KeitaroError("upstream_not_found", "Campaign was not found")
        stream_id = self._next_stream_id
        self._next_stream_id += 1
        stream = deepcopy(payload) | {
            "id": stream_id,
            "campaign_id": campaign_id,
            "updated_at": _now(),
        }
        self.streams[campaign_id].append(stream)
        return deepcopy(stream)

    def update_stream(self, stream_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        if self.fail_next_update:
            self.fail_next_update = False
            raise KeitaroError("upstream_rejected", "Simulated Keitaro failure", retryable=True)
        for streams in self.streams.values():
            for stream in streams:
                if stream["id"] == stream_id:
                    stream.update(deepcopy(payload))
                    stream["updated_at"] = _now()
                    return deepcopy(stream)
        raise KeitaroError("upstream_not_found", "Stream was not found")

    def mutate_remote_offers(self, stream_id: int, offers: list[dict[str, Any]]) -> None:
        self.update_stream(stream_id, {"offers": offers})
