import logging

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.models import Campaign, IdempotencyRecord

logger = logging.getLogger(__name__)


def prepare_runtime(
    settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    if settings.keitaro_mode != "fake":
        return
    with session_factory() as session:
        session.execute(delete(IdempotencyRecord))
        session.execute(delete(Campaign))
        session.commit()
    logger.info("fake_mode_local_state_reset")


def main() -> None:
    prepare_runtime(get_settings(), SessionLocal)


if __name__ == "__main__":
    main()
