import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-with-at-least-32-bytes"
os.environ["APP_ENV"] = "test"
os.environ["QWEN_BASE_URL"] = ""
os.environ["QWEN_API_KEY"] = ""
os.environ["QWEN_MODEL"] = ""
os.environ["EMBEDDING_BASE_URL"] = ""
os.environ["EMBEDDING_API_KEY"] = ""

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

import pytest
from app.db import Base, engine
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
