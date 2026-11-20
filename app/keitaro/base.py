from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class KeitaroOffer:
    id: int
    name: str
    state: str = "active"


class KeitaroError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        outcome_unknown: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.outcome_unknown = outcome_unknown


class KeitaroClient(Protocol):
    def list_offers(self) -> list[dict[str, Any]]: ...

    def get_campaign(self, campaign_id: int) -> dict[str, Any]: ...

    def create_campaign(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def get_streams(self, campaign_id: int) -> list[dict[str, Any]]: ...

    def create_stream(self, campaign_id: int, payload: dict[str, Any]) -> dict[str, Any]: ...

    def update_stream(self, stream_id: int, payload: dict[str, Any]) -> dict[str, Any]: ...
