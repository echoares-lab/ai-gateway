"""Release identity contract for the Gateway Engine."""

from fastapi.testclient import TestClient

from core.release_metadata import release_metadata


FULL_SHA = "0123456789abcdef0123456789abcdef01234567"


def test_release_metadata_uses_injected_version_and_full_sha(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "1.2.1")
    monkeypatch.setenv("GIT_SHA", FULL_SHA)

    assert release_metadata() == {
        "version": "1.2.1",
        "git_sha": FULL_SHA,
        "display_version": "1.2.1+sha.0123456",
    }


def test_release_metadata_has_traceable_local_defaults(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.delenv("GIT_SHA", raising=False)

    assert release_metadata() == {
        "version": "0.0.0-dev",
        "git_sha": "unknown",
        "display_version": "0.0.0-dev+sha.unknown",
    }


def test_version_endpoint_returns_release_metadata(monkeypatch):
    import main

    monkeypatch.setenv("APP_VERSION", "1.2.1")
    monkeypatch.setenv("GIT_SHA", FULL_SHA)

    response = TestClient(main.app).get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "version": "1.2.1",
        "git_sha": FULL_SHA,
        "display_version": "1.2.1+sha.0123456",
    }
