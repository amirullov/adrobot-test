from app.config import Settings
from app.keitaro.payloads import KeitaroPayloadBuilder


def test_payload_builder_keeps_version_sensitive_fields_in_one_place() -> None:
    settings = Settings(
        keitaro_domain_id=7,
        keitaro_group_id=8,
        keitaro_traffic_source_id=9,
        keitaro_google_url="https://www.google.com/",
    )
    builder = KeitaroPayloadBuilder(settings)

    campaign = builder.campaign(name="US Aurora Search")
    assert campaign["alias"] == "us-aurora-search"
    assert campaign["domain_id"] == 7
    assert campaign["group_id"] == "8"
    assert campaign["traffic_source_id"] == 9

    google = builder.google_stream(country_code="US")
    assert google["schema"] == "redirect"
    assert google["filters"] == [{"name": "country", "mode": "accept", "payload": ["US"]}]
    assert google["action_payload"] == "https://www.google.com/"

    offer = builder.offer_stream(offers=[{"offer_id": 101, "share": 100}])
    assert offer["schema"] == "landings"
    assert offer["action_type"] == "http"

    update = builder.update_offers([{"offer_id": 101, "share": 100}])
    assert update == {"offers": [{"offer_id": 101, "share": 100, "state": "active"}]}
