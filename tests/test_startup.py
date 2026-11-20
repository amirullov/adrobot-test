from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.models import Base, Campaign, IdempotencyRecord
from app.startup import prepare_runtime


def test_fake_mode_resets_local_mirror() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(
            Campaign(
                keitaro_campaign_id=9001,
                name="Stale fake campaign",
                country_code="US",
                google_stream_id=1,
                offer_stream_id=2,
                server_snapshot=[],
                remote_fingerprint="x" * 64,
            )
        )
        session.add(
            IdempotencyRecord(
                operation="create_campaign",
                key="stale-key",
                request_hash="y" * 64,
                status="succeeded",
            )
        )
        session.commit()

    prepare_runtime(Settings(keitaro_mode="fake"), factory)

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Campaign)) == 0
        assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0


def test_http_mode_preserves_local_state() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(
            IdempotencyRecord(
                operation="create_campaign",
                key="kept-key",
                request_hash="z" * 64,
                status="in_progress",
            )
        )
        session.commit()

    prepare_runtime(
        Settings(keitaro_mode="http", keitaro_api_key="secret"), factory
    )

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1
