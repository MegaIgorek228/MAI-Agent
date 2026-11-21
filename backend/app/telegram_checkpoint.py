from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, SessionLocal


class TelegramCheckpoint(Base):
    __tablename__ = "telegram_checkpoints"

    bot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    next_offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False)


def read_checkpoint(bot_id: str) -> tuple[int, int]:
    with SessionLocal() as db:
        checkpoint = db.get(TelegramCheckpoint, bot_id)
        if checkpoint is None:
            return 0, 0
        return checkpoint.next_offset, checkpoint.failed_attempts


def save_checkpoint(bot_id: str, offset: int, failed_attempts: int) -> None:
    with SessionLocal() as db:
        checkpoint = db.get(TelegramCheckpoint, bot_id)
        if checkpoint is None:
            checkpoint = TelegramCheckpoint(bot_id=bot_id)
            db.add(checkpoint)
        checkpoint.next_offset = offset
        checkpoint.failed_attempts = failed_attempts
        db.commit()
