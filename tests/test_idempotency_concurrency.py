from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.errors import ConflictError
from app.keitaro.fake import FakeKeitaroClient
from app.models import Base, IdempotencyRecord
from app.schemas import CampaignCreate
from app.services import CampaignService


def test_simultaneous_same_key_creates_remote_campaign_once(tmp_path: Path) -> None:
    database_path = tmp_path / "concurrency.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    fake = FakeKeitaroClient()
    barrier = Barrier(2)

    class RacingService(CampaignService):
        def __init__(self, db: Session) -> None:
            super().__init__(
                db, fake, Settings(database_url=f"sqlite:///{database_path}")
            )
            self.waited = False

        def _find_creation_record(
            self, idempotency_key: str, *, lock: bool = False
        ) -> IdempotencyRecord | None:
            result = super()._find_creation_record(idempotency_key, lock=lock)
            if result is None and not self.waited:
                self.waited = True
                barrier.wait(timeout=5)
            return result

    data = CampaignCreate(name="Concurrent", country_code="US", offer_id=101)

    def create() -> tuple[str, int | None]:
        with factory() as session:
            try:
                campaign = RacingService(session).create_campaign(data, "same-key-001")
                return "success", campaign.id
            except ConflictError as exc:
                return exc.code, None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: create(), range(2)))

    assert all(result[0] in {"success", "creation_already_attempted"} for result in results)
    assert any(result[0] == "success" for result in results)
    assert len(fake.campaigns) == 2  # seeded demo plus exactly one new campaign
