from app.services.source_feed_pipeline import get_resonnet_base_url


def test_get_resonnet_base_url_defaults_to_internal_backend_url(monkeypatch):
    monkeypatch.delenv("RESONNET_BASE_URL", raising=False)
    monkeypatch.setenv("BACKEND_PORT", "8010")

    assert get_resonnet_base_url() == "http://backend:8000"


def test_get_resonnet_base_url_uses_explicit_override(monkeypatch):
    monkeypatch.setenv("RESONNET_BASE_URL", "http://127.0.0.1:8010/")

    assert get_resonnet_base_url() == "http://127.0.0.1:8010"
