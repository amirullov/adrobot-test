from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.keitaro.fake import FakeKeitaroClient
from app.models import Campaign


def import_demo(client: TestClient) -> dict[str, object]:
    response = client.post("/api/campaigns/import", json={"keitaro_campaign_id": 5001})
    assert response.status_code == 201
    return response.json()


def test_create_campaign_is_idempotent(client: TestClient, fake_keitaro: FakeKeitaroClient) -> None:
    payload = {"name": "US Aurora", "country_code": "us", "offer_id": 101}
    headers = {"Idempotency-Key": "test-create-0001"}
    first = client.post("/api/campaigns", json=payload, headers=headers)
    second = client.post("/api/campaigns", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    campaign_id = first.json()["keitaro_campaign_id"]
    streams = fake_keitaro.get_streams(campaign_id)
    assert len(streams) == 2
    assert streams[0]["action_payload"] == "https://www.google.com/"
    assert streams[1]["offers"] == [{"offer_id": 101, "share": 100, "state": "active"}]


def test_same_idempotency_key_cannot_change_body(client: TestClient) -> None:
    headers = {"Idempotency-Key": "test-create-0002"}
    assert client.post(
        "/api/campaigns",
        json={"name": "A", "country_code": "US", "offer_id": 101},
        headers=headers,
    ).status_code == 201
    response = client.post(
        "/api/campaigns",
        json={"name": "B", "country_code": "US", "offer_id": 101},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_key_reused"


def test_remove_bring_back_and_cancel_are_local(
    client: TestClient, fake_keitaro: FakeKeitaroClient
) -> None:
    campaign = import_demo(client)
    local_id = campaign["id"]
    version = campaign["draft_version"]
    original_remote = fake_keitaro.get_streams(5001)[1]["offers"]

    removed = client.delete(
        f"/api/campaigns/{local_id}/draft/offers/101?version={version}"
    ).json()
    assert removed["dirty"] is True
    assert [row["share"] for row in removed["rows"]] == [0, 50, 50]
    assert removed["rows"][0]["state"] == "removed"
    assert fake_keitaro.get_streams(5001)[1]["offers"] == original_remote

    restored = client.post(
        f"/api/campaigns/{local_id}/draft/offers/101/bring-back",
        json={"version": removed["draft_version"]},
    ).json()
    assert restored["dirty"] is False
    assert [row["share"] for row in restored["rows"]] == [34, 33, 33]

    added = client.post(
        f"/api/campaigns/{local_id}/draft/offers",
        json={"offer_id": 104, "version": restored["draft_version"]},
    ).json()
    cancelled = client.post(
        f"/api/campaigns/{local_id}/draft/cancel",
        json={"version": added["draft_version"]},
    ).json()
    assert cancelled["dirty"] is False
    assert [row["offer_id"] for row in cancelled["rows"]] == [101, 102, 103]


def test_successful_push_updates_remote_and_clears_draft(
    client: TestClient, fake_keitaro: FakeKeitaroClient
) -> None:
    campaign = import_demo(client)
    added = client.post(
        f"/api/campaigns/{campaign['id']}/draft/offers",
        json={"offer_id": 104, "version": campaign["draft_version"]},
    ).json()
    pushed = client.post(
        f"/api/campaigns/{campaign['id']}/push",
        json={"version": added["draft_version"]},
    )
    assert pushed.status_code == 200
    body = pushed.json()
    assert body["dirty"] is False
    assert [row["share"] for row in body["rows"]] == [25, 25, 25, 25]
    assert [item["share"] for item in fake_keitaro.get_streams(5001)[1]["offers"]] == [25] * 4


def test_failed_push_keeps_draft(client: TestClient, fake_keitaro: FakeKeitaroClient) -> None:
    campaign = import_demo(client)
    added = client.post(
        f"/api/campaigns/{campaign['id']}/draft/offers",
        json={"offer_id": 104, "version": campaign["draft_version"]},
    ).json()
    fake_keitaro.fail_next_update = True
    response = client.post(
        f"/api/campaigns/{campaign['id']}/push",
        json={"version": added["draft_version"]},
    )
    assert response.status_code == 502
    current = client.get(f"/api/campaigns/{campaign['id']}").json()
    assert current["dirty"] is True
    assert [row["offer_id"] for row in current["rows"]] == [101, 102, 103, 104]


def test_remote_change_blocks_push_and_keeps_draft(
    client: TestClient, fake_keitaro: FakeKeitaroClient
) -> None:
    campaign = import_demo(client)
    added = client.post(
        f"/api/campaigns/{campaign['id']}/draft/offers",
        json={"offer_id": 104, "version": campaign["draft_version"]},
    ).json()
    fake_keitaro.mutate_remote_offers(
        6002,
        [
            {"offer_id": 101, "share": 50, "state": "active"},
            {"offer_id": 102, "share": 50, "state": "active"},
        ],
    )
    response = client.post(
        f"/api/campaigns/{campaign['id']}/push",
        json={"version": added["draft_version"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "remote_changed"
    assert client.get(f"/api/campaigns/{campaign['id']}").json()["dirty"] is True


def test_stale_version_and_push_guard(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    campaign = import_demo(client)
    stale = client.post(
        f"/api/campaigns/{campaign['id']}/draft/offers",
        json={"offer_id": 104, "version": campaign["draft_version"] + 1},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_draft"

    added = client.post(
        f"/api/campaigns/{campaign['id']}/draft/offers",
        json={"offer_id": 104, "version": campaign["draft_version"]},
    ).json()
    with session_factory() as session:
        model = session.scalar(select(Campaign).where(Campaign.id == campaign["id"]))
        assert model is not None
        model.syncing = True
        session.commit()
    guarded = client.post(
        f"/api/campaigns/{campaign['id']}/push",
        json={"version": added["draft_version"]},
    )
    assert guarded.status_code == 409
    assert guarded.json()["error"]["code"] == "push_in_progress"


def test_zero_active_offers_cannot_be_pushed(client: TestClient) -> None:
    campaign = import_demo(client)
    version = campaign["draft_version"]
    for offer_id in [101, 102, 103]:
        response = client.delete(
            f"/api/campaigns/{campaign['id']}/draft/offers/{offer_id}?version={version}"
        )
        assert response.status_code == 200
        version = response.json()["draft_version"]
    pushed = client.post(
        f"/api/campaigns/{campaign['id']}/push", json={"version": version}
    )
    assert pushed.status_code == 422
    assert pushed.json()["error"]["code"] == "empty_offer_stream"
