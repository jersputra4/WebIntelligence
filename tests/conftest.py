import dataclasses
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import load_settings  # noqa: E402
from app.main import create_app  # noqa: E402

TEST_KEY = "test-secret-key-123"


@pytest.fixture
def make_settings(tmp_path):
    def _make(**overrides):
        base = dataclasses.replace(
            load_settings(),
            ensembledata_api_key=TEST_KEY,
            ensembledata_base_url="https://ensembledata.test/apis",
            provider_mode_setting="live",
            request_retries=0,
            rate_limit_requests=100,
            database_path=tmp_path / "test.db",
        )
        return dataclasses.replace(base, **overrides)
    return _make


@pytest.fixture
def make_client(make_settings):
    clients = []

    def _make(handler=None, **overrides):
        transport = httpx.MockTransport(handler) if handler else None
        client = TestClient(create_app(make_settings(**overrides), transport=transport))
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)
