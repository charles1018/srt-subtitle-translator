"""CLI 測試。"""

from types import SimpleNamespace
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


def test_create_parser_accepts_prompt_subcommands() -> None:
    """CLI parser 應接受 prompt 管理子命令。"""
    parser = cli.create_parser()

    show_args = parser.parse_args(["prompt", "show", "--provider", "google", "--content-type", "anime"])
    assert show_args.command == "prompt"
    assert show_args.prompt_command == "show"
    assert show_args.provider == "google"
    assert show_args.content_type == "anime"

    set_args = parser.parse_args(["prompt", "set", "--provider", "llamacpp", "--text", "test prompt"])
    assert set_args.prompt_command == "set"
    assert set_args.provider == "llamacpp"
    assert set_args.text == "test prompt"

    export_args = parser.parse_args(["prompt", "export", "-o", "/tmp/prompt.json"])
    assert export_args.prompt_command == "export"
    assert export_args.output == "/tmp/prompt.json"


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


def test_cmd_prompt_show_displays_selected_prompt(capsys) -> None:
    """prompt show 應讀取並輸出指定提示詞。"""
    parser = cli.create_parser()
    args = parser.parse_args(["prompt", "show", "--provider", "google", "--content-type", "anime"])

    mock_prompt_manager = MagicMock()
    mock_prompt_manager.get_prompt.return_value = "google anime prompt"

    with patch.object(cli.PromptManager, "get_instance", return_value=mock_prompt_manager):
        result = cli.cmd_prompt(args)

    assert result == 0
    mock_prompt_manager.get_prompt.assert_called_once_with("google", "anime")
    assert capsys.readouterr().out.strip() == "google anime prompt"


def test_cmd_prompt_set_reads_prompt_file(tmp_path, capsys) -> None:
    """prompt set 應能從檔案讀取提示詞內容。"""
    parser = cli.create_parser()
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("custom prompt from file", encoding="utf-8")
    args = parser.parse_args(
        ["prompt", "set", "--provider", "google", "--content-type", "movie", "--file", str(prompt_file)]
    )

    mock_prompt_manager = MagicMock()
    mock_prompt_manager.current_content_type = "general"

    with patch.object(cli.PromptManager, "get_instance", return_value=mock_prompt_manager):
        result = cli.cmd_prompt(args)

    assert result == 0
    mock_prompt_manager.set_prompt.assert_called_once_with("custom prompt from file", "google", "movie")
    assert capsys.readouterr().out.strip() == "已更新 movie/google 提示詞"


def test_cmd_prompt_export_supports_all_providers(capsys) -> None:
    """prompt export 未指定 provider 時應交由 PromptManager 匯出全部。"""
    parser = cli.create_parser()
    args = parser.parse_args(["prompt", "export", "--content-type", "anime", "-o", "/tmp/prompts.json"])

    mock_prompt_manager = MagicMock()
    mock_prompt_manager.export_prompt.return_value = "/tmp/prompts.json"

    with patch.object(cli.PromptManager, "get_instance", return_value=mock_prompt_manager):
        result = cli.cmd_prompt(args)

    assert result == 0
    mock_prompt_manager.export_prompt.assert_called_once_with("anime", None, file_path="/tmp/prompts.json")
    assert capsys.readouterr().out.strip() == "提示詞已匯出到: /tmp/prompts.json"


def test_cmd_prompt_import_runs_prompt_manager(capsys) -> None:
    """prompt import 應呼叫 PromptManager 匯入。"""
    parser = cli.create_parser()
    args = parser.parse_args(["prompt", "import", "/tmp/prompts.json"])

    mock_prompt_manager = MagicMock()
    mock_prompt_manager.import_prompt.return_value = True

    with patch.object(cli.PromptManager, "get_instance", return_value=mock_prompt_manager):
        result = cli.cmd_prompt(args)

    assert result == 0
    mock_prompt_manager.import_prompt.assert_called_once_with("/tmp/prompts.json")
    assert capsys.readouterr().out.strip() == "已匯入提示詞: /tmp/prompts.json"


def test_cmd_qa_returns_zero_and_prints_summary(capsys) -> None:
    """qa 成功時應輸出摘要並回傳 0。"""
    parser = cli.create_parser()
    args = parser.parse_args(["qa", "source.srt", "target.srt"])

    qa_result = SimpleNamespace(
        is_valid=True,
        source_count=12,
        target_count=12,
        errors=[],
        warnings=[],
    )

    with patch("srt_translator.tools.srt_tools.qa", return_value=qa_result) as mock_qa:
        result = cli.cmd_qa(args)

    assert result == 0
    mock_qa.assert_called_once_with("source.srt", "target.srt")
    output = capsys.readouterr().out
    assert "來源字幕: 12 個" in output
    assert "目標字幕: 12 個" in output
    assert "QA 通過" in output


def test_cmd_qa_strict_mode_fails_on_warning(capsys) -> None:
    """qa 在 strict 模式下遇到警告應回傳非 0。"""
    parser = cli.create_parser()
    args = parser.parse_args(["qa", "source.srt", "target.srt", "--strict"])

    qa_result = SimpleNamespace(
        is_valid=True,
        source_count=8,
        target_count=8,
        errors=[],
        warnings=["Index 不匹配 #1: 來源=1, 目標=2"],
    )

    with patch("srt_translator.tools.srt_tools.qa", return_value=qa_result):
        result = cli.cmd_qa(args)

    assert result == 1
    output = capsys.readouterr().out
    assert "警告:" in output
    assert "QA 失敗（嚴格模式：有警告）" in output


def test_cmd_qa_with_cps_runs_audit_report(capsys) -> None:
    """qa --cps 應附加執行 CPS 審計並輸出報告。"""
    parser = cli.create_parser()
    args = parser.parse_args(["qa", "source.srt", "target.srt", "--cps"])

    qa_result = SimpleNamespace(
        is_valid=True,
        source_count=5,
        target_count=5,
        errors=[],
        warnings=[],
    )
    cps_report = SimpleNamespace(
        total_subtitles=5,
        problematic_count=1,
        avg_cps=6.2,
        max_cps=19.5,
        summary={"high_cps": 1, "long_line": 0, "too_many_lines": 0, "short_duration": 0},
        entries=[SimpleNamespace(index=3, text="測試字幕", issues=["CPS=19.5 (>17.0)"])],
    )

    with (
        patch("srt_translator.tools.srt_tools.qa", return_value=qa_result),
        patch("srt_translator.tools.srt_tools.cps_audit", return_value=cps_report) as mock_cps_audit,
    ):
        result = cli.cmd_qa(args)

    assert result == 0
    mock_cps_audit.assert_called_once_with("target.srt", max_cps=17.0, max_line_length=22)
    output = capsys.readouterr().out
    assert "--- CPS/可讀性審計 ---" in output
    assert "總字幕數: 5" in output
    assert "問題字幕: 1" in output


def test_cmd_cps_audit_returns_nonzero_when_problematic(capsys) -> None:
    """cps-audit 有問題字幕時應回傳非 0 並印出摘要。"""
    parser = cli.create_parser()
    args = parser.parse_args(["cps-audit", "target.srt"])

    cps_report = SimpleNamespace(
        total_subtitles=10,
        problematic_count=2,
        avg_cps=5.9,
        max_cps=21.3,
        summary={"high_cps": 1, "long_line": 0, "too_many_lines": 1, "short_duration": 0},
        entries=[
            SimpleNamespace(index=2, text="第一句", issues=["CPS=21.3 (>17.0)"]),
            SimpleNamespace(index=4, text="第二句", issues=["行數=3 (>2)"]),
        ],
    )

    with patch("srt_translator.tools.srt_tools.cps_audit", return_value=cps_report) as mock_cps_audit:
        result = cli.cmd_cps_audit(args)

    assert result == 1
    mock_cps_audit.assert_called_once_with(
        "target.srt",
        max_cps=17.0,
        max_line_length=22,
        max_lines=2,
        min_duration_ms=1000,
    )
    output = capsys.readouterr().out
    assert "總字幕數: 10" in output
    assert "問題字幕: 2" in output
    assert "問題字幕詳情" in output
