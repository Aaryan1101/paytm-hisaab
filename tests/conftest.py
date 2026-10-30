import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401  (register tables)
from app.seed.loader import seed_all


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session():
    """Empty in-memory database."""
    with Session(_engine()) as s:
        yield s


@pytest.fixture
def seeded():
    """Fresh seeded database + context. Function scoped so tests may mutate freely."""
    with Session(_engine()) as s:
        ctx = seed_all(s)
        s.commit()
        yield s, ctx


@pytest.fixture
def api(seeded, tmp_path):
    """(TestClient, session, ctx, fakes) with a seeded DB and fake Sarvam ports."""
    from fastapi.testclient import TestClient

    from app.container import Container
    from app.db import get_session
    from app.main import create_app
    from app.storage import MediaStore
    from tests.fakes import FakeChat, FakeDocAI, FakeStt, FakeTts

    s, ctx = seeded
    fakes = type("Fakes", (), {})()
    fakes.chat = FakeChat([])
    fakes.docai, fakes.stt, fakes.tts = FakeDocAI({}), FakeStt(), FakeTts()
    container = Container(fakes.chat, fakes.docai, fakes.stt, fakes.tts, MediaStore(str(tmp_path), "http://testserver"))
    app = create_app(container)
    app.dependency_overrides[get_session] = lambda: s
    fakes.container = container
    yield TestClient(app), s, ctx, fakes


@pytest.fixture(params=["native", "graph"])
def engine_api(request, seeded, tmp_path):
    """Like `api`, but the same tests run once per agent engine."""
    from fastapi.testclient import TestClient

    from app.container import Container
    from app.db import get_session
    from app.main import create_app
    from app.storage import MediaStore
    from tests.fakes import FakeChat, FakeDocAI, FakeStt, FakeTts

    s, ctx = seeded
    fakes = type("Fakes", (), {})()
    fakes.chat, fakes.docai, fakes.stt, fakes.tts = FakeChat([]), FakeDocAI({}), FakeStt(), FakeTts()
    fakes.container = Container(fakes.chat, fakes.docai, fakes.stt, fakes.tts, MediaStore(str(tmp_path), "http://testserver"),
                                agent_engine=request.param)
    app = create_app(fakes.container)
    app.dependency_overrides[get_session] = lambda: s
    fakes.engine = request.param
    yield TestClient(app), s, ctx, fakes
