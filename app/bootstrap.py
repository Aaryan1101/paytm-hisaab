"""First-run setup: create tables and seed the demo data when the database is empty."""
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, select

import app.models  # noqa: F401  (register tables)
from app.models import Merchant
from app.seed.loader import seed_all


def ensure_seeded(engine: Engine) -> bool:
    """Return True if it had to seed."""
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if session.exec(select(Merchant)).first() is not None:
            return False
        seed_all(session)
        session.commit()
        return True
