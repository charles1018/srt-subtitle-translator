"""Tests for GUI app preflight checks."""

from unittest.mock import AsyncMock, MagicMock, patch

from srt_translator.__main__ import App


def test_validate_translation_request_for_ollama_includes_configured_url():
    """Ollama 預檢失敗時，應回報目前設定的服務位址。"""
    app = App.__new__(App)
    app.model_service = MagicMock()
    app.model_service.test_model_connection = AsyncMock(
        return_value={"success": False, "message": "連線失敗: name resolution error"}
    )

    with patch("srt_translator.__main__.get_config", return_value="http://newhost:11434"):
        is_valid, message = app._validate_translation_request("ollama", "mistral")

    assert is_valid is False
    assert "http://newhost:11434" in message
    assert "ollama_url" in message


def test_validate_translation_request_for_remote_provider_checks_network():
    """遠端提供者仍應維持網路連線檢查。"""
    app = App.__new__(App)
    app.model_service = MagicMock()

    with patch("srt_translator.__main__.check_internet_connection", return_value=False):
        is_valid, message = app._validate_translation_request("openai", "gpt-4o-mini")

    assert is_valid is False
    assert "網路連線異常" in message
