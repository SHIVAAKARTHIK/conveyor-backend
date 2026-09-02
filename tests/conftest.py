import os
from pathlib import Path

# Point the app at a throwaway SQLite file BEFORE any `app.*` module is
# imported, so tests never touch dev.db or a real MySQL database.
TEST_DB_PATH = Path(__file__).parent / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ["FIREBASE_SERVICE_ACCOUNT_PATH"] = ""

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)
