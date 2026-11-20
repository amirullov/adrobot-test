from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_db
from app.keitaro.base import KeitaroClient
from app.models import Campaign
from app.schemas import (
    CampaignCreate,
    CampaignImport,
    CampaignView,
    DraftOfferAdd,
    DraftVersion,
    OfferView,
)
from app.services import CampaignService

router = APIRouter(prefix="/api")


def get_service(
    request: Request, db: Annotated[Session, Depends(get_db)]
) -> CampaignService:
    return CampaignService(
        db,
        cast(KeitaroClient, request.app.state.keitaro),
        cast(Settings, request.app.state.settings),
    )


Service = Annotated[CampaignService, Depends(get_service)]


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    settings = cast(Settings, request.app.state.settings)
    return {"status": "ok", "keitaro_mode": settings.keitaro_mode}


@router.get("/offers", response_model=list[OfferView])
def list_offers(
    service: Service, q: str = Query(default="", max_length=100)
) -> list[dict[str, object]]:
    return service.list_offers(q)


@router.get("/campaigns", response_model=list[CampaignView])
def list_campaigns(service: Service) -> list[CampaignView]:
    campaigns = list(service.db.scalars(select(Campaign).order_by(Campaign.id.desc())))
    return [service.view(campaign) for campaign in campaigns]


@router.post("/campaigns", response_model=CampaignView, status_code=status.HTTP_201_CREATED)
def create_campaign(
    data: CampaignCreate,
    service: Service,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> CampaignView:
    return service.view(service.create_campaign(data, idempotency_key))


@router.post("/campaigns/import", response_model=CampaignView, status_code=status.HTTP_201_CREATED)
def import_campaign(data: CampaignImport, service: Service) -> CampaignView:
    return service.view(service.import_campaign(data.keitaro_campaign_id))


@router.get("/campaigns/{campaign_id}", response_model=CampaignView)
def get_campaign(campaign_id: int, service: Service) -> CampaignView:
    return service.view(service._campaign(campaign_id))


@router.post("/campaigns/{campaign_id}/fetch", response_model=CampaignView)
def fetch_campaign(campaign_id: int, service: Service) -> CampaignView:
    return service.view(service.fetch(campaign_id))


@router.post("/campaigns/{campaign_id}/draft/offers", response_model=CampaignView)
def add_offer(campaign_id: int, data: DraftOfferAdd, service: Service) -> CampaignView:
    return service.view(service.add_offer(campaign_id, data.offer_id, data.version))


@router.delete(
    "/campaigns/{campaign_id}/draft/offers/{offer_id}", response_model=CampaignView
)
def remove_offer(
    campaign_id: int,
    offer_id: int,
    service: Service,
    version: int = Query(ge=0),
) -> CampaignView:
    return service.view(service.remove_offer(campaign_id, offer_id, version))


@router.post(
    "/campaigns/{campaign_id}/draft/offers/{offer_id}/bring-back",
    response_model=CampaignView,
)
def bring_back(
    campaign_id: int, offer_id: int, data: DraftVersion, service: Service
) -> CampaignView:
    return service.view(service.bring_back(campaign_id, offer_id, data.version))


@router.post("/campaigns/{campaign_id}/draft/cancel", response_model=CampaignView)
def cancel_draft(campaign_id: int, data: DraftVersion, service: Service) -> CampaignView:
    return service.view(service.cancel(campaign_id, data.version))


@router.post("/campaigns/{campaign_id}/push", response_model=CampaignView)
def push_campaign(campaign_id: int, data: DraftVersion, service: Service) -> CampaignView:
    return service.view(service.push(campaign_id, data.version))
