import re
from dataclasses import dataclass
from typing import Any

from app.config import Settings


@dataclass(frozen=True, slots=True)
class KeitaroPayloadBuilder:
    """Contains every version-sensitive Keitaro payload assumption."""

    settings: Settings

    def campaign(self, *, name: str) -> dict[str, Any]:
        alias = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "campaign"
        return {
            "name": name,
            "alias": alias[:64],
            "type": "position",
            "state": "active",
            "domain_id": self.settings.keitaro_domain_id,
            "group_id": str(self.settings.keitaro_group_id),
            "traffic_source_id": self.settings.keitaro_traffic_source_id,
        }

    def google_stream(self, *, country_code: str) -> dict[str, Any]:
        return {
            "name": f"{country_code} → Google",
            "schema": "redirect",
            "type": "regular",
            "position": 1,
            "state": "active",
            "action_type": self.settings.keitaro_redirect_action_type,
            "action_payload": self.settings.keitaro_google_url,
            "filter_or": False,
            "filters": [
                {
                    "name": self.settings.keitaro_country_filter_name,
                    "mode": "accept",
                    "payload": [country_code],
                }
            ],
        }

    def offer_stream(self, *, offers: list[dict[str, int]]) -> dict[str, Any]:
        return {
            "name": "Offers",
            "schema": "landings",
            "type": "default",
            "position": 2,
            "state": "active",
            "action_type": self.settings.keitaro_offer_action_type,
            "offers": [
                {"offer_id": item["offer_id"], "share": item["share"], "state": "active"}
                for item in offers
            ],
        }

    def update_offers(self, offers: list[dict[str, int]]) -> dict[str, Any]:
        return {
            "offers": [
                {"offer_id": item["offer_id"], "share": item["share"], "state": "active"}
                for item in offers
            ]
        }
