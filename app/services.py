import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError, ConflictError, NotFoundError
from app.keitaro.base import KeitaroClient, KeitaroError
from app.keitaro.payloads import KeitaroPayloadBuilder
from app.models import Campaign, IdempotencyRecord
from app.schemas import CampaignCreate, CampaignView, OfferRow


def allocate_shares(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = [dict(row) for row in rows]
    active_indexes = [index for index, row in enumerate(result) if row["state"] == "active"]
    count = len(active_indexes)
    if count == 0:
        for row in result:
            row["share"] = 0
        return result
    base, remainder = divmod(100, count)
    for row in result:
        row["share"] = 0
    for position, row_index in enumerate(active_indexes):
        result[row_index]["share"] = base + (1 if position < remainder else 0)
    return result


def stream_fingerprint(stream: dict[str, Any]) -> str:
    editable = {
        "action_type": stream.get("action_type"),
        "offers": [
            {
                "offer_id": int(item["offer_id"]),
                "share": int(item.get("share", 0)),
                "state": item.get("state", "active"),
            }
            for item in stream.get("offers", [])
        ],
        "updated_at": stream.get("updated_at"),
    }
    encoded = json.dumps(editable, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def request_hash(data: dict[str, Any]) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class CampaignService:
    def __init__(
        self, db: Session, keitaro: KeitaroClient, settings: Settings
    ) -> None:
        self.db = db
        self.keitaro = keitaro
        self.settings = settings
        self.payloads = KeitaroPayloadBuilder(settings)

    def _campaign(self, campaign_id: int, *, lock: bool = False) -> Campaign:
        statement = select(Campaign).where(Campaign.id == campaign_id)
        if lock:
            statement = statement.with_for_update()
        campaign = self.db.scalar(statement)
        if campaign is None:
            raise NotFoundError("Campaign was not found")
        return campaign

    def _offers_by_id(self) -> dict[int, dict[str, Any]]:
        return {int(item["id"]): item for item in self.keitaro.list_offers()}

    def _normalize_stream(
        self, stream: dict[str, Any], offers_by_id: dict[int, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in stream.get("offers", []):
            offer_id = int(item["offer_id"])
            offer = offers_by_id.get(offer_id, {})
            state = "active" if item.get("state", "active") == "active" else "removed"
            rows.append(
                {
                    "offer_id": offer_id,
                    "name": str(offer.get("name", f"Offer #{offer_id}")),
                    "state": state,
                    "share": int(item.get("share", 0)) if state == "active" else 0,
                }
            )
        return allocate_shares(rows)

    @staticmethod
    def _country_from_stream(stream: dict[str, Any]) -> str:
        for item in stream.get("filters", []):
            if item.get("name") == "country":
                payload = item.get("payload", [])
                if isinstance(payload, list) and payload:
                    return str(payload[0]).upper()[:2]
                if isinstance(payload, str) and payload:
                    return payload.upper()[:2]
        return "ZZ"

    def _remote_stream(self, campaign: Campaign) -> dict[str, Any]:
        streams = self.keitaro.get_streams(campaign.keitaro_campaign_id)
        try:
            return next(item for item in streams if int(item["id"]) == campaign.offer_stream_id)
        except StopIteration as exc:
            raise AppError(
                "offer_stream_missing",
                "The configured offer stream no longer exists in Keitaro",
                status_code=409,
            ) from exc

    def list_offers(self, query: str = "") -> list[dict[str, Any]]:
        needle = query.strip().lower()
        offers = [item for item in self.keitaro.list_offers() if item.get("state") == "active"]
        if needle:
            offers = [
                item
                for item in offers
                if needle in str(item.get("name", "")).lower()
                or needle in str(item.get("id", ""))
            ]
        return [
            {"id": int(item["id"]), "name": str(item["name"]), "state": "active"}
            for item in offers[:100]
        ]

    def _find_creation_record(
        self, idempotency_key: str, *, lock: bool = False
    ) -> IdempotencyRecord | None:
        statement = select(IdempotencyRecord).where(
            IdempotencyRecord.operation == "create_campaign",
            IdempotencyRecord.key == idempotency_key,
        )
        if lock:
            statement = statement.with_for_update()
        return self.db.scalar(statement)

    def _resolve_creation_record(
        self, record: IdempotencyRecord, body_hash: str
    ) -> tuple[IdempotencyRecord, Campaign | None]:
        if record.request_hash != body_hash:
            raise ConflictError(
                "idempotency_key_reused",
                "This idempotency key was already used for a different request",
            )
        if record.status == "succeeded" and record.response:
            return record, self._campaign(int(record.response["local_campaign_id"]))
        if record.status == "failed_safe":
            record.status = "in_progress"
            record.response = None
            self.db.commit()
            return record, None
        if record.status == "rejected":
            response = record.response or {}
            raise AppError(
                str(response.get("code", "creation_rejected")),
                str(response.get("message", "Campaign creation was rejected")),
                status_code=422,
            )
        raise ConflictError(
            "creation_already_attempted",
            "This creation key is in progress or has an uncertain outcome; "
            "inspect Keitaro before using a new key",
            details=record.response,
        )

    def _claim_creation(
        self, idempotency_key: str, body_hash: str
    ) -> tuple[IdempotencyRecord, Campaign | None]:
        existing = self._find_creation_record(idempotency_key, lock=True)
        if existing is not None:
            return self._resolve_creation_record(existing, body_hash)

        record = IdempotencyRecord(
            operation="create_campaign",
            key=idempotency_key,
            request_hash=body_hash,
            status="in_progress",
        )
        self.db.add(record)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            winner = self._find_creation_record(idempotency_key, lock=True)
            if winner is None:
                raise
            return self._resolve_creation_record(winner, body_hash)
        return record, None

    def create_campaign(self, data: CampaignCreate, idempotency_key: str) -> Campaign:
        body = data.model_dump()
        body_hash = request_hash(body)
        record, completed = self._claim_creation(idempotency_key, body_hash)
        if completed is not None:
            return completed

        try:
            offers = self._offers_by_id()
        except KeitaroError as exc:
            record.status = "failed_safe"
            record.response = {
                "code": exc.code,
                "created": {},
                "outcome_unknown": False,
            }
            self.db.commit()
            raise AppError(
                exc.code,
                f"Keitaro preflight failed: {exc.message}. No remote changes were attempted.",
                status_code=502,
                retryable=exc.retryable,
                details=record.response,
            ) from exc
        offer = offers.get(data.offer_id)
        if offer is None or offer.get("state") != "active":
            record.status = "rejected"
            record.response = {
                "code": "offer_not_found",
                "message": "The selected active offer does not exist",
            }
            self.db.commit()
            raise AppError(
                "offer_not_found",
                "The selected active offer does not exist",
                status_code=422,
            )

        created_ids: dict[str, int] = {}
        try:
            remote_campaign = self.keitaro.create_campaign(self.payloads.campaign(name=data.name))
            kt_campaign_id = int(remote_campaign["id"])
            created_ids["campaign_id"] = kt_campaign_id
            google_stream = self.keitaro.create_stream(
                kt_campaign_id, self.payloads.google_stream(country_code=data.country_code)
            )
            created_ids["google_stream_id"] = int(google_stream["id"])
            initial_rows = allocate_shares(
                [{"offer_id": data.offer_id, "name": str(offer["name"]), "state": "active"}]
            )
            offer_stream = self.keitaro.create_stream(
                kt_campaign_id,
                self.payloads.offer_stream(
                    offers=[{"offer_id": data.offer_id, "share": 100}]
                ),
            )
            created_ids["offer_stream_id"] = int(offer_stream["id"])
        except KeitaroError as exc:
            outcome_unknown = bool(created_ids) or exc.outcome_unknown
            record.status = "outcome_unknown" if outcome_unknown else "failed_safe"
            record.response = {
                "code": exc.code,
                "created": created_ids,
                "outcome_unknown": outcome_unknown,
            }
            self.db.commit()
            error_code = (
                "creation_partially_failed"
                if created_ids
                else "creation_outcome_unknown"
                if exc.outcome_unknown
                else exc.code
            )
            raise AppError(
                error_code,
                "Campaign creation did not complete. Inspect Keitaro before retrying."
                if outcome_unknown
                else exc.message,
                status_code=502,
                retryable=exc.retryable and not outcome_unknown,
                details=record.response,
            ) from exc

        campaign = Campaign(
            keitaro_campaign_id=kt_campaign_id,
            name=data.name,
            country_code=data.country_code,
            google_stream_id=int(google_stream["id"]),
            offer_stream_id=int(offer_stream["id"]),
            server_snapshot=initial_rows,
            remote_fingerprint=stream_fingerprint(offer_stream),
            remote_updated_at=offer_stream.get("updated_at"),
        )
        self.db.add(campaign)
        self.db.flush()
        record.status = "succeeded"
        record.response = {"local_campaign_id": campaign.id, "created": created_ids}
        self.db.commit()
        return campaign

    def import_campaign(self, keitaro_campaign_id: int) -> Campaign:
        existing = self.db.scalar(
            select(Campaign).where(Campaign.keitaro_campaign_id == keitaro_campaign_id)
        )
        if existing:
            return existing
        remote = self.keitaro.get_campaign(keitaro_campaign_id)
        streams = self.keitaro.get_streams(keitaro_campaign_id)
        candidates = [
            item
            for item in streams
            if item.get("offers") or item.get("schema") == "landings"
        ]
        if len(candidates) != 1:
            raise AppError(
                "offer_stream_ambiguous",
                "Expected exactly one offer stream; configure/import this campaign manually",
                status_code=422,
                details={"candidate_stream_ids": [item.get("id") for item in candidates]},
            )
        offer_stream = candidates[0]
        google_stream = next(
            (
                item
                for item in streams
                if item.get("action_payload") == self.settings.keitaro_google_url
            ),
            None,
        )
        rows = self._normalize_stream(offer_stream, self._offers_by_id())
        country = self._country_from_stream(google_stream or {})
        campaign = Campaign(
            keitaro_campaign_id=keitaro_campaign_id,
            name=str(remote.get("name", f"Campaign #{keitaro_campaign_id}")),
            country_code=country,
            google_stream_id=int(google_stream["id"]) if google_stream else None,
            offer_stream_id=int(offer_stream["id"]),
            server_snapshot=rows,
            remote_fingerprint=stream_fingerprint(offer_stream),
            remote_updated_at=offer_stream.get("updated_at"),
        )
        self.db.add(campaign)
        self.db.commit()
        return campaign

    def fetch(self, campaign_id: int) -> Campaign:
        campaign = self._campaign(campaign_id, lock=True)
        if campaign.draft is not None:
            raise ConflictError(
                "dirty_draft",
                "Cancel or push local changes before fetching remote state",
            )
        stream = self._remote_stream(campaign)
        campaign.server_snapshot = self._normalize_stream(stream, self._offers_by_id())
        campaign.remote_fingerprint = stream_fingerprint(stream)
        campaign.remote_updated_at = stream.get("updated_at")
        campaign.draft_version += 1
        campaign.last_error = None
        self.db.commit()
        return campaign

    def _check_version(self, campaign: Campaign, version: int) -> None:
        if campaign.draft_version != version:
            raise ConflictError(
                "stale_draft",
                "The draft changed in another request. Reload before continuing.",
                details={"current_version": campaign.draft_version},
            )

    def _save_draft(self, campaign: Campaign, rows: list[dict[str, Any]]) -> Campaign:
        rows = allocate_shares(rows)
        campaign.draft = None if rows == campaign.server_snapshot else rows
        campaign.draft_version += 1
        campaign.last_error = None
        self.db.commit()
        return campaign

    def add_offer(self, campaign_id: int, offer_id: int, version: int) -> Campaign:
        campaign = self._campaign(campaign_id, lock=True)
        self._check_version(campaign, version)
        rows = [dict(row) for row in (campaign.draft or campaign.server_snapshot)]
        existing = next((row for row in rows if int(row["offer_id"]) == offer_id), None)
        if existing:
            existing["state"] = "active"
        else:
            offer = self._offers_by_id().get(offer_id)
            if offer is None or offer.get("state") != "active":
                raise AppError(
                    "offer_not_found",
                    "The selected active offer does not exist",
                    status_code=422,
                )
            rows.append(
                {"offer_id": offer_id, "name": str(offer["name"]), "state": "active", "share": 0}
            )
        return self._save_draft(campaign, rows)

    def remove_offer(self, campaign_id: int, offer_id: int, version: int) -> Campaign:
        campaign = self._campaign(campaign_id, lock=True)
        self._check_version(campaign, version)
        rows = [dict(row) for row in (campaign.draft or campaign.server_snapshot)]
        row = next((item for item in rows if int(item["offer_id"]) == offer_id), None)
        if row is None:
            raise NotFoundError("Offer is not part of this campaign")
        row["state"] = "removed"
        return self._save_draft(campaign, rows)

    def bring_back(self, campaign_id: int, offer_id: int, version: int) -> Campaign:
        campaign = self._campaign(campaign_id, lock=True)
        self._check_version(campaign, version)
        rows = [dict(row) for row in (campaign.draft or campaign.server_snapshot)]
        row = next((item for item in rows if int(item["offer_id"]) == offer_id), None)
        if row is None:
            raise NotFoundError("Offer is not part of this campaign")
        row["state"] = "active"
        return self._save_draft(campaign, rows)

    def cancel(self, campaign_id: int, version: int) -> Campaign:
        campaign = self._campaign(campaign_id, lock=True)
        self._check_version(campaign, version)
        campaign.draft = None
        campaign.last_error = None
        campaign.draft_version += 1
        self.db.commit()
        return campaign

    def push(self, campaign_id: int, version: int) -> Campaign:
        campaign = self._campaign(campaign_id, lock=True)
        self._check_version(campaign, version)
        if campaign.syncing:
            raise ConflictError("push_in_progress", "A push is already in progress")
        if campaign.draft is None:
            raise ConflictError("draft_not_dirty", "There are no local changes to push")
        active = [row for row in campaign.draft if row["state"] == "active"]
        if not active:
            raise AppError(
                "empty_offer_stream",
                "At least one active offer is required before pushing",
                status_code=422,
            )
        campaign.syncing = True
        campaign.last_error = None
        self.db.commit()

        try:
            remote = self._remote_stream(campaign)
            current_fingerprint = stream_fingerprint(remote)
            if current_fingerprint != campaign.remote_fingerprint:
                raise ConflictError(
                    "remote_changed",
                    "Keitaro changed since the draft was loaded. "
                    "Your draft was kept; inspect and refetch.",
                )
            payload_rows = [
                {"offer_id": int(row["offer_id"]), "share": int(row["share"])}
                for row in active
            ]
            updated = self.keitaro.update_stream(
                campaign.offer_stream_id, self.payloads.update_offers(payload_rows)
            )
        except ConflictError:
            campaign.syncing = False
            campaign.last_error = "Keitaro changed outside this application"
            self.db.commit()
            raise
        except KeitaroError as exc:
            campaign.syncing = False
            campaign.last_error = exc.message
            self.db.commit()
            raise AppError(
                exc.code,
                (
                    "Push outcome is unknown; inspect Keitaro before trying again. "
                    "The local draft was kept."
                    if exc.outcome_unknown
                    else f"Push failed: {exc.message}. The local draft was kept."
                ),
                status_code=502,
                retryable=exc.retryable and not exc.outcome_unknown,
                details={"outcome_unknown": exc.outcome_unknown},
            ) from exc

        draft_offers = {
            int(row["offer_id"]): {"id": int(row["offer_id"]), "name": str(row["name"])}
            for row in campaign.draft
        }
        campaign.server_snapshot = self._normalize_stream(updated, draft_offers)
        campaign.draft = None
        campaign.remote_fingerprint = stream_fingerprint(updated)
        campaign.remote_updated_at = updated.get("updated_at")
        campaign.syncing = False
        campaign.last_error = None
        campaign.draft_version += 1
        self.db.commit()
        return campaign

    def view(self, campaign: Campaign) -> CampaignView:
        rows = campaign.draft if campaign.draft is not None else campaign.server_snapshot
        url = self.settings.keitaro_admin_campaign_url_template.format(
            base_url=self.settings.keitaro_base_url,
            campaign_id=campaign.keitaro_campaign_id,
        )
        return CampaignView(
            id=campaign.id,
            keitaro_campaign_id=campaign.keitaro_campaign_id,
            name=campaign.name,
            country_code=campaign.country_code,
            google_stream_id=campaign.google_stream_id,
            offer_stream_id=campaign.offer_stream_id,
            rows=[OfferRow.model_validate(row) for row in rows],
            dirty=campaign.draft is not None,
            syncing=campaign.syncing,
            draft_version=campaign.draft_version,
            last_error=campaign.last_error,
            keitaro_url=url,
        )
