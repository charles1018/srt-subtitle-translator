"""CLI 測試。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from srt_translator import cli


def test_normalize_display_mode_alias() -> None:
    """CLI 應將舊顯示模式別名轉為 runtime 使用值。"""
    assert cli.normalize_display_mode("僅譯文") == "僅顯示翻譯"
    assert cli.normalize_display_mode("翻譯在上") == "翻譯在上"


def test_create_parser_accepts_runtime_display_modes() -> None:
    """CLI parser 應接受 GUI/runtime 使用的顯示模式。"""
    parser = cli.create_parser()

    args = parser.parse_args(["translate", "input.srt", "-s", "日文", "-t", "繁體中文", "--display-mode", "翻譯在上"])
    assert args.display_mode == "翻譯在上"

    alias_args = parser.parse_args(
        ["translate", "input.srt", "-s", "日文", "-t", "繁體中文", "--display-mode", "僅譯文"]
    )
    assert alias_args.display_mode == "僅譯文"


def test_create_parser_accepts_google_and_prompt_flags() -> None:
    """CLI parser 應接受 google provider 與 GUI 對應的翻譯設定。"""
    parser = cli.create_parser()

    args = parser.parse_args(
        [
            "translate",
            "input.srt",
            "-s",
            "日文",
            "-t",
            "繁體中文",
            "--provider",
            "google",
            "--content-type",
            "anime",
            "--style",
            "localized",
            "--netflix-style",
        ]
    )

    assert args.provider == "google"
    assert args.content_type == "anime"
    assert args.style == "localized"
    assert args.netflix_style is True


@pytest.mark.asyncio
async def test_cmd_translate_aligns_runtime_flags() -> None:
    """cmd_translate 應傳遞正確的 runtime 顯示模式、輸出目錄與快取設定。"""
    parser = cli.create_parser()
    args = parser.parse_args(
        [
            "translate",
            "input.srt",
            "-s",
            "日文",
            "-t",
            "繁體中文",
            "--display-mode",
            "僅譯文",
            "--output-dir",
            "/tmp/output",
            "--no-cache",
        ]
    )

    mock_translation_service = MagicMock()
    mock_translation_service.translate_subtitle_file = AsyncMock(return_value=(True, "/tmp/output/input.zh_tw.srt"))
    mock_model_service = MagicMock()
    mock_model_service.get_recommended_model.return_value = "llama3.2"
    mock_file_service = MagicMock()

    with (
        patch.object(cli, "collect_files", return_value=["/tmp/input.srt"]),
        patch.object(cli.ServiceFactory, "get_translation_service", return_value=mock_translation_service),
        patch.object(cli.ServiceFactory, "get_model_service", return_value=mock_model_service),
        patch.object(cli.ServiceFactory, "get_file_service", return_value=mock_file_service),
        patch.object(cli.ServiceFactory, "reset_services"),
    ):
        result = await cli.cmd_translate(args)

    assert result == 0
    mock_file_service.set_batch_settings.assert_called_once_with({"output_directory": "/tmp/output"})
    mock_translation_service.translate_subtitle_file.assert_awaited_once()
    call_kwargs = mock_translation_service.translate_subtitle_file.await_args.kwargs
    assert call_kwargs["display_mode"] == "僅顯示翻譯"
    assert call_kwargs["use_cache"] is False


@pytest.mark.asyncio
async def test_cmd_translate_applies_cli_translation_overrides() -> None:
    """cmd_translate 應套用內容類型、風格與 Netflix 風格覆寫。"""
    parser = cli.create_parser()
    args = parser.parse_args(
        [
            "translate",
            "input.srt",
            "-s",
            "日文",
            "-t",
            "繁體中文",
            "--provider",
            "google",
            "--content-type",
            "anime",
            "--style",
            "localized",
            "--netflix-style",
        ]
    )

    mock_prompt_manager = MagicMock()
    mock_prompt_manager.config_manager = MagicMock()
    mock_translation_service = MagicMock()
    mock_translation_service.prompt_manager = mock_prompt_manager
    mock_translation_service.translate_subtitle_file = AsyncMock(return_value=(True, "/tmp/output/input.zh_tw.srt"))
    mock_model_service = MagicMock()
    mock_model_service.get_recommended_model.return_value = "gemini-2.0-flash"
    mock_user_config = MagicMock()

    with (
        patch.object(cli, "collect_files", return_value=["/tmp/input.srt"]),
        patch.object(cli.ServiceFactory, "get_translation_service", return_value=mock_translation_service),
        patch.object(cli.ServiceFactory, "get_model_service", return_value=mock_model_service),
        patch.object(cli.ServiceFactory, "reset_services"),
        patch.object(cli.ConfigManager, "get_instance", return_value=mock_user_config),
    ):
        result = await cli.cmd_translate(args)

    assert result == 0
    assert mock_prompt_manager.current_content_type == "anime"
    assert mock_prompt_manager.current_style == "localized"
    mock_prompt_manager.config_manager.set_value.assert_any_call("current_content_type", "anime", auto_save=False)
    mock_prompt_manager.config_manager.set_value.assert_any_call("current_style", "localized", auto_save=False)
    mock_user_config.set_value.assert_called_once_with("netflix_style_enabled", True, auto_save=False)
