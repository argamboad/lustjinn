import pytest
from fastapi.testclient import TestClient

from lustjinn.main import app

client = TestClient(app)


def test_health_answers_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_the_deployed_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_GIT_COMMIT", "3d36977")

    assert client.get("/health").json()["commit"] == "3d36977"


def test_health_reports_no_commit_off_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)

    assert client.get("/health").json() == {"status": "ok", "commit": None}
