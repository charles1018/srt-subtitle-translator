"""CLI 模組 - 提供命令列介面支援腳本自動化和批次處理"""

import argparse
import asyncio
import logging
import os
import sys
from typing import List, Optional

from srt_translator.core.config import ConfigManager
from srt_translator.services.factory import ServiceFactory
from srt_translator.utils import format_exception

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("SRTTranslator.CLI")


def create_parser() -> argparse.ArgumentParser:
    """建立命令列參數解析器"""
    parser = argparse.ArgumentParser(
        prog="srt-translator",
        description="SRT 字幕翻譯工具 - 支援 Ollama、OpenAI、Anthropic API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  # 翻譯單一檔案
  srt-translator translate video.srt -s 日文 -t 繁體中文

  # 批次翻譯目錄下所有字幕
  srt-translator translate ./subtitles/ -s 英文 -t 繁體中文

  # 使用 OpenAI 翻譯
  srt-translator translate video.srt -s 日文 -t 繁體中文 --provider openai --model gpt-4o

  # 顯示可用模型
  srt-translator models --provider ollama

  # 顯示快取統計
  srt-translator cache --stats

  # 清除快取
  srt-translator cache --clear

  # 建立術語表
  srt-translator glossary create anime -s 日文 -t 繁體中文

  # 新增術語
  srt-translator glossary add anime "進撃の巨人" "進擊的巨人"

  # 使用術語表翻譯
  srt-translator translate video.srt -s 日文 -t 繁體中文 -g anime
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="可用指令")

    # translate 子命令
    translate_parser = subparsers.add_parser("translate", help="翻譯字幕檔案")
    translate_parser.add_argument("input", nargs="+", help="輸入檔案或目錄路徑")
    translate_parser.add_argument("-s", "--source", required=True, help="來源語言 (如: 日文, 英文)")
    translate_parser.add_argument("-t", "--target", required=True, help="目標語言 (如: 繁體中文)")
    translate_parser.add_argument(
        "-p", "--provider", default="ollama", choices=["ollama", "openai", "anthropic"], help="LLM 提供者 (預設: ollama)"
    )
    translate_parser.add_argument("-m", "--model", help="模型名稱 (未指定則使用推薦模型)")
    translate_parser.add_argument(
        "-d",
        "--display-mode",
        default="僅譯文",
        choices=["僅譯文", "雙語對照", "僅原文"],
        help="顯示模式 (預設: 僅譯文)",
    )
    translate_parser.add_argument("-c", "--concurrency", type=int, default=3, help="並行請求數 (預設: 3)")
    translate_parser.add_argument("-o", "--output-dir", help="輸出目錄 (預設: 與輸入檔案同目錄)")
    translate_parser.add_argument("--no-cache", action="store_true", help="不使用翻譯快取")
    translate_parser.add_argument("-g", "--glossary", action="append", help="使用指定術語表 (可多次指定)")
    translate_parser.add_argument("-q", "--quiet", action="store_true", help="安靜模式，僅顯示錯誤")
    translate_parser.add_argument("-v", "--verbose", action="store_true", help="詳細輸出模式")

    # models 子命令
    models_parser = subparsers.add_parser("models", help="列出可用模型")
    models_parser.add_argument(
        "-p", "--provider", default="ollama", choices=["ollama", "openai", "anthropic"], help="LLM 提供者"
    )

    # cache 子命令
    cache_parser = subparsers.add_parser("cache", help="管理翻譯快取")
    cache_group = cache_parser.add_mutually_exclusive_group(required=True)
    cache_group.add_argument("--stats", action="store_true", help="顯示快取統計資訊")
    cache_group.add_argument("--clear", action="store_true", help="清除所有快取")
    cache_group.add_argument("--optimize", action="store_true", help="最佳化快取資料庫")
    cache_group.add_argument("--export", metavar="FILE", help="匯出快取到指定檔案")
    cache_group.add_argument("--import", metavar="FILE", dest="import_file", help="從指定檔案匯入快取")

    # config 子命令
    config_parser = subparsers.add_parser("config", help="顯示或設定配置")
    config_parser.add_argument("--show", action="store_true", help="顯示目前配置")
    config_parser.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), help="設定配置值")

    # glossary 子命令
    glossary_parser = subparsers.add_parser("glossary", help="管理術語表")
    glossary_subparsers = glossary_parser.add_subparsers(dest="glossary_command", help="術語表操作")

    # glossary list
    glossary_subparsers.add_parser("list", help="列出所有術語表")

    # glossary create
    glossary_create = glossary_subparsers.add_parser("create", help="建立新術語表")
    glossary_create.add_argument("name", help="術語表名稱")
    glossary_create.add_argument("-s", "--source", default="", help="來源語言")
    glossary_create.add_argument("-t", "--target", default="", help="目標語言")
    glossary_create.add_argument("-d", "--description", default="", help="說明")

    # glossary show
    glossary_show = glossary_subparsers.add_parser("show", help="顯示術語表內容")
    glossary_show.add_argument("name", help="術語表名稱")

    # glossary add
    glossary_add = glossary_subparsers.add_parser("add", help="新增術語")
    glossary_add.add_argument("glossary", help="術語表名稱")
    glossary_add.add_argument("source", help="來源術語")
    glossary_add.add_argument("target", help="目標翻譯")
    glossary_add.add_argument("-c", "--category", default="", help="分類")
    glossary_add.add_argument("-n", "--notes", default="", help="備註")

    # glossary remove
    glossary_remove = glossary_subparsers.add_parser("remove", help="移除術語")
    glossary_remove.add_argument("glossary", help="術語表名稱")
    glossary_remove.add_argument("source", help="來源術語")

    # glossary delete
    glossary_delete = glossary_subparsers.add_parser("delete", help="刪除術語表")
    glossary_delete.add_argument("name", help="術語表名稱")

    # glossary import
    glossary_import = glossary_subparsers.add_parser("import", help="匯入術語表")
    glossary_import.add_argument("file", help="檔案路徑 (支援 .json, .csv, .txt)")
    glossary_import.add_argument("-n", "--name", help="術語表名稱 (預設使用檔案名稱)")

    # glossary export
    glossary_export = glossary_subparsers.add_parser("export", help="匯出術語表")
    glossary_export.add_argument("name", help="術語表名稱")
    glossary_export.add_argument("file", help="輸出檔案路徑")
    glossary_export.add_argument("-f", "--format", choices=["json", "csv", "txt"], default="json", help="輸出格式")

    # glossary activate/deactivate
    glossary_activate = glossary_subparsers.add_parser("activate", help="啟用術語表")
    glossary_activate.add_argument("name", help="術語表名稱")

    glossary_deactivate = glossary_subparsers.add_parser("deactivate", help="停用術語表")
    glossary_deactivate.add_argument("name", help="術語表名稱")

    # version 子命令
    subparsers.add_parser("version", help="顯示版本資訊")

    return parser


def collect_files(paths: List[str]) -> List[str]:
    """收集所有要翻譯的檔案"""
    files = []
    supported_extensions = {".srt", ".vtt", ".ass", ".ssa"}

    for path in paths:
        if os.path.isfile(path):
            ext = os.path.splitext(path)[1].lower()
            if ext in supported_extensions:
                files.append(os.path.abspath(path))
            else:
                logger.warning(f"不支援的檔案格式: {path}")
        elif os.path.isdir(path):
            for root, _, filenames in os.walk(path):
                for filename in filenames:
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in supported_extensions:
                        files.append(os.path.abspath(os.path.join(root, filename)))
        else:
            logger.warning(f"路徑不存在: {path}")

    return files


def print_progress(current: int, total: int, extra_data: Optional[dict] = None) -> None:
    """在終端顯示翻譯進度"""
    if total <= 0:
        return

    percentage = int((current / total) * 100)
    bar_length = 40
    filled_length = int(bar_length * current / total)
    bar = "█" * filled_length + "░" * (bar_length - filled_length)

    # 使用 \r 來覆蓋同一行
    sys.stdout.write(f"\r進度: [{bar}] {percentage}% ({current}/{total})")
    sys.stdout.flush()

    if current == total:
        sys.stdout.write("\n")
        sys.stdout.flush()


async def cmd_translate(args: argparse.Namespace) -> int:
    """執行翻譯命令"""
    # 設定日誌級別
    if args.quiet:
        logging.getLogger().setLevel(logging.ERROR)
    elif args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 收集檔案
    files = collect_files(args.input)
    if not files:
        logger.error("找不到可翻譯的字幕檔案")
        return 1

    logger.info(f"找到 {len(files)} 個檔案待翻譯")

    # 取得服務
    translation_service = ServiceFactory.get_translation_service()
    model_service = ServiceFactory.get_model_service()

    # 決定模型
    model_name = args.model
    if not model_name:
        model_name = model_service.get_recommended_model("translation", args.provider)
        logger.info(f"使用推薦模型: {model_name}")

    # 設定輸出目錄
    if args.output_dir:
        file_service = ServiceFactory.get_file_service()
        file_service.set_batch_settings({"output_dir": args.output_dir})

    # 啟用指定的術語表
    if args.glossary:
        from srt_translator.core.glossary import get_glossary_manager

        glossary_manager = get_glossary_manager()
        for glossary_name in args.glossary:
            if glossary_manager.activate_glossary(glossary_name):
                logger.info(f"已啟用術語表: {glossary_name}")
            else:
                logger.warning(f"找不到術語表: {glossary_name}")

    # 翻譯每個檔案
    success_count = 0
    fail_count = 0

    for i, file_path in enumerate(files, 1):
        filename = os.path.basename(file_path)
        logger.info(f"[{i}/{len(files)}] 翻譯: {filename}")

        try:
            # 進度回調
            progress_callback = None if args.quiet else print_progress

            success, result = await translation_service.translate_subtitle_file(
                file_path=file_path,
                source_lang=args.source,
                target_lang=args.target,
                model_name=model_name,
                parallel_requests=args.concurrency,
                display_mode=args.display_mode,
                llm_type=args.provider,
                progress_callback=progress_callback,
            )

            if success:
                logger.info(f"✓ 完成: {result}")
                success_count += 1
            else:
                logger.error(f"✗ 失敗: {result}")
                fail_count += 1

        except Exception as e:
            logger.error(f"✗ 翻譯失敗: {format_exception(e)}")
            fail_count += 1

    # 顯示摘要
    logger.info(f"\n翻譯完成: 成功 {success_count} 個, 失敗 {fail_count} 個")

    # 清理資源
    ServiceFactory.reset_services()

    return 0 if fail_count == 0 else 1


async def cmd_models(args: argparse.Namespace) -> int:
    """列出可用模型"""
    model_service = ServiceFactory.get_model_service()

    try:
        models = await model_service.get_available_models(args.provider)
        if models:
            print(f"\n{args.provider} 可用模型:")
            print("-" * 40)
            for model in models:
                print(f"  • {model}")
            print()
        else:
            print(f"\n{args.provider} 沒有可用的模型")
    except Exception as e:
        logger.error(f"無法取得模型列表: {format_exception(e)}")
        return 1
    finally:
        ServiceFactory.reset_services()

    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    """管理快取"""
    cache_service = ServiceFactory.get_cache_service()

    try:
        if args.stats:
            stats = cache_service.get_cache_stats()
            print("\n快取統計:")
            print("-" * 40)
            print(f"  總筆數: {stats.get('total_entries', 0)}")
            print(f"  資料庫大小: {stats.get('db_size_mb', 0):.2f} MB")
            print(f"  最近使用: {stats.get('last_used', 'N/A')}")
            print()

        elif args.clear:
            confirm = input("確定要清除所有快取嗎？(y/N): ")
            if confirm.lower() == "y":
                cache_service.clear_all_cache()
                print("快取已清除")
            else:
                print("取消操作")

        elif args.optimize:
            cache_service.optimize_database()
            print("快取資料庫已最佳化")

        elif args.export:
            cache_service.export_cache(args.export)
            print(f"快取已匯出至: {args.export}")

        elif args.import_file:
            cache_service.import_cache(args.import_file)
            print(f"快取已從 {args.import_file} 匯入")

    except Exception as e:
        logger.error(f"快取操作失敗: {format_exception(e)}")
        return 1
    finally:
        ServiceFactory.reset_services()

    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """顯示或設定配置"""
    user_config = ConfigManager.get_instance("user")

    if args.show:
        config = user_config.get_config()
        print("\n目前配置:")
        print("-" * 40)
        for key, value in config.items():
            print(f"  {key}: {value}")
        print()

    elif args.set:
        key, value = args.set
        # 嘗試轉換數值
        if value.isdigit():
            value = int(value)
        elif value.lower() in ("true", "false"):
            value = value.lower() == "true"

        user_config.set_value(key, value)
        print(f"已設定 {key} = {value}")

    return 0



def cmd_glossary(args: argparse.Namespace) -> int:
    """管理術語表"""
    from srt_translator.core.glossary import get_glossary_manager

    manager = get_glossary_manager()

    if args.glossary_command is None:
        print("請指定術語表操作，使用 --help 查看可用選項")
        return 1

    if args.glossary_command == "list":
        glossaries = manager.list_glossaries()
        if glossaries:
            print("\n術語表列表:")
            print("-" * 50)
            for name in glossaries:
                glossary = manager.get_glossary(name)
                if glossary:
                    active = "✓" if name in manager.get_active_glossaries() else " "
                    print(f"  [{active}] {name} ({len(glossary.entries)} 條目)")
                    if glossary.source_lang or glossary.target_lang:
                        print(f"      {glossary.source_lang} → {glossary.target_lang}")
            print()
        else:
            print("\n目前沒有任何術語表\n")

    elif args.glossary_command == "create":
        try:
            glossary = manager.create_glossary(
                name=args.name,
                source_lang=args.source,
                target_lang=args.target,
                description=args.description,
            )
            print(f"已建立術語表: {glossary.name}")
        except ValueError as e:
            logger.error(str(e))
            return 1

    elif args.glossary_command == "show":
        glossary = manager.get_glossary(args.name)
        if not glossary:
            logger.error(f"找不到術語表: {args.name}")
            return 1

        print(f"\n術語表: {glossary.name}")
        print("-" * 50)
        if glossary.description:
            print(f"說明: {glossary.description}")
        if glossary.source_lang:
            print(f"來源語言: {glossary.source_lang}")
        if glossary.target_lang:
            print(f"目標語言: {glossary.target_lang}")
        print(f"條目數: {len(glossary.entries)}")
        print()

        if glossary.entries:
            print("條目:")
            for entry in glossary.entries.values():
                line = f"  {entry.source} → {entry.target}"
                if entry.category:
                    line += f" [{entry.category}]"
                print(line)
        print()

    elif args.glossary_command == "add":
        if manager.add_entry_to_glossary(
            glossary_name=args.glossary,
            source=args.source,
            target=args.target,
            category=args.category,
            notes=args.notes,
        ):
            print(f"已新增術語: {args.source} → {args.target}")
        else:
            logger.error(f"找不到術語表: {args.glossary}")
            return 1

    elif args.glossary_command == "remove":
        if manager.remove_entry_from_glossary(args.glossary, args.source):
            print(f"已移除術語: {args.source}")
        else:
            logger.error(f"找不到術語或術語表: {args.glossary}/{args.source}")
            return 1

    elif args.glossary_command == "delete":
        confirm = input(f"確定要刪除術語表 '{args.name}' 嗎？(y/N): ")
        if confirm.lower() == "y":
            if manager.delete_glossary(args.name):
                print(f"已刪除術語表: {args.name}")
            else:
                logger.error(f"找不到術語表: {args.name}")
                return 1
        else:
            print("取消操作")

    elif args.glossary_command == "import":
        name = getattr(args, "name", None)
        glossary = manager.import_glossary(args.file, name=name)
        if glossary:
            print(f"已匯入術語表: {glossary.name} ({len(glossary.entries)} 條目)")
        else:
            return 1

    elif args.glossary_command == "export":
        if manager.export_glossary(args.name, args.file, args.format):
            print(f"已匯出術語表到: {args.file}")
        else:
            return 1

    elif args.glossary_command == "activate":
        if manager.activate_glossary(args.name):
            print(f"已啟用術語表: {args.name}")
        else:
            logger.error(f"找不到術語表: {args.name}")
            return 1

    elif args.glossary_command == "deactivate":
        if manager.deactivate_glossary(args.name):
            print(f"已停用術語表: {args.name}")
        else:
            logger.error(f"術語表未啟用或不存在: {args.name}")
            return 1

    return 0

def cmd_version() -> int:
    """顯示版本資訊"""
    try:
        from importlib.metadata import version

        ver = version("srt-subtitle-translator")
    except Exception:
        ver = "unknown"

    print(f"SRT Subtitle Translator v{ver}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """CLI 主程式入口"""
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    # 確保必要目錄存在
    for directory in ["data", "config", "logs"]:
        os.makedirs(directory, exist_ok=True)

    # 執行對應命令
    if args.command == "translate":
        return asyncio.run(cmd_translate(args))
    elif args.command == "models":
        return asyncio.run(cmd_models(args))
    elif args.command == "cache":
        return cmd_cache(args)
    elif args.command == "config":
        return cmd_config(args)
    elif args.command == "glossary":
        return cmd_glossary(args)
    elif args.command == "version":
        return cmd_version()
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
