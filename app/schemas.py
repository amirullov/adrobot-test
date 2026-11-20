from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OfferView(BaseModel):
    id: int
    name: str
    state: str = "active"


class OfferRow(BaseModel):
    offer_id: int
    name: str
    state: str = "active"
    share: int = 0


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    country_code: str
    offer_id: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Campaign name cannot be blank")
        return value

    @field_validator("country_code")
    @classmethod
    def clean_country(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 2 or not value.isalpha() or not value.isascii():
            raise ValueError("Use a two-letter ISO country code, for example US")
        return value


class CampaignImport(BaseModel):
    keitaro_campaign_id: int = Field(gt=0)


class DraftVersion(BaseModel):
    version: int = Field(ge=0)


class DraftOfferAdd(DraftVersion):
    offer_id: int = Field(gt=0)


class CampaignView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    keitaro_campaign_id: int
    name: str
    country_code: str
    google_stream_id: int | None
    offer_stream_id: int
    rows: list[OfferRow]
    dirty: bool
    syncing: bool
    draft_version: int
    last_error: str | None
    keitaro_url: str


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
