"""Tests for GUI app preflight checks."""

from unittest.mock import AsyncMock, MagicMock, patch

from srt_translator.__main__ import App


def test_init_services_does_not_require_legacy_file_api_key_loader():
    """初始化服務時不應再依賴 FileService 的舊 OpenAI-only key loader。"""
    app = App.__new__(App)
    file_service = MagicMock(spec=[])
    model_service = MagicMock()
    translation_service = MagicMock()
    cache_service = MagicMock()

    with (
        patch.object(app, "_ensure_directories"),
        patch("srt_translator.__main__.ServiceFactory.get_file_service", return_value=file_service),
        patch("srt_translator.__main__.ServiceFactory.get_model_service", return_value=model_service),
        patch("srt_translator.__main__.ServiceFactory.get_translation_service", return_value=translation_service),
        patch("srt_translator.__main__.ServiceFactory.get_cache_service", return_value=cache_service),
        patch("srt_translator.__main__.TranslationTaskManager", return_value=MagicMock()),
        patch("srt_translator.__main__.ConfigManager.get_instance", side_effect=[MagicMock(), MagicMock()]),
    ):
        app._init_services()

    assert app.file_service is file_service
    assert app.model_service is model_service
    assert app.translation_service is translation_service
    assert app.cache_service is cache_service


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
    """遠端 provider 在連線前仍應先檢查網路。"""
    app = App.__new__(App)
    app.model_service = MagicMock()

    with patch("srt_translator.__main__.check_internet_connection", return_value=False):
        is_valid, message = app._validate_translation_request("openai", "gpt-4o-mini")

    assert is_valid is False
    assert "網路連線異常" in message


def test_validate_translation_request_for_openai_requires_api_key():
    """OpenAI 預檢應在缺少金鑰時直接阻擋。"""
    app = App.__new__(App)
    app.model_service = MagicMock()
    app.model_service.api_keys = {}

    with patch("srt_translator.__main__.check_internet_connection", return_value=True):
        is_valid, message = app._validate_translation_request("openai", "gpt-4o-mini")

    assert is_valid is False
    assert "OPENAI_API_KEY" in message


def test_validate_translation_request_for_google_reports_connection_failure():
    """Google 預檢失敗時應回報 provider-specific 訊息。"""
    app = App.__new__(App)
    app.model_service = MagicMock()
    app.model_service.api_keys = {"google": "test-google-key"}
    app.model_service.test_model_connection = MagicMock(return_value="google-preflight")
    app._run_async_in_new_loop = MagicMock(return_value={"success": False, "message": "API 金鑰無效或認證失敗"})

    with patch("srt_translator.__main__.check_internet_connection", return_value=True):
        is_valid, message = app._validate_translation_request("google", "gemini-2.5-flash")

    assert is_valid is False
    assert "Google Gemini 連線失敗" in message
    assert "API 金鑰無效或認證失敗" in message
    app._run_async_in_new_loop.assert_called_once_with("google-preflight")


def test_validate_translation_request_for_llamacpp_uses_server_check_not_network():
    """llama.cpp 應檢查本地 server，而不是被一般網路檢查短路。"""
    app = App.__new__(App)
    app.model_service = MagicMock()
    app.model_service.api_keys = {}
    app.model_service.test_model_connection = MagicMock(return_value="llamacpp-preflight")
    app._run_async_in_new_loop = MagicMock(return_value={"success": False, "message": "連線失敗: connection refused"})

    with (
        patch("srt_translator.__main__.check_internet_connection", return_value=False),
        patch("srt_translator.__main__.get_config", return_value="http://localhost:8088"),
    ):
        is_valid, message = app._validate_translation_request("llamacpp", "Qwen3.5-9B-UD")

    assert is_valid is False
    assert "llama.cpp 連線失敗" in message
    assert "http://localhost:8088" in message
    assert "網路連線異常" not in message
    app._run_async_in_new_loop.assert_called_once_with("llamacpp-preflight")
