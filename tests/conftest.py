from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Base, get_db
from app.keitaro.fake import FakeKeitaroClient
from app.main import create_app


@pytest.fixture
def fake_keitaro() -> FakeKeitaroClient:
    return FakeKeitaroClient()


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def client(
    session_factory: sessionmaker[Session], fake_keitaro: FakeKeitaroClient
) -> Generator[TestClient, None, None]:
    settings = Settings(database_url="sqlite://", keitaro_mode="fake")
    application = create_app(settings=settings, keitaro=fake_keitaro)

    def override_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as test_client:
        yield test_client
