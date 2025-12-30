import logging
import logging.handlers
import os
import re
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from queue import Queue
from tkinter import filedialog, messagebox
from typing import Any, Dict, List, Optional

import chardet

# Try importing tkinterdnd2
try:
    from tkinterdnd2 import *  # noqa: F403 - Dynamic import for optional drag-drop support

    TKDND_AVAILABLE = True
except ImportError:
    TKDND_AVAILABLE = False

# Try importing subtitle related packages
try:
    import pysrt

    PYSRT_AVAILABLE = True
except ImportError:
    PYSRT_AVAILABLE = False

try:
    import webvtt

    WEBVTT_AVAILABLE = True
except ImportError:
    WEBVTT_AVAILABLE = False

# Import from configuration manager
from srt_translator.core.config import ConfigManager
from srt_translator.utils import FileError, format_exception

# Setup logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Use custom attribute to mark configured loggers (more reliable than checking handlers)
if not getattr(logger, "_file_handler_configured", False):
    # Ensure logs directory exists
    os.makedirs("logs", exist_ok=True)

    # Avoid adding handlers multiple times (double-check)
    if not logger.handlers:
        handler = logging.handlers.TimedRotatingFileHandler(
            filename="logs/file_handler.log", when="midnight", interval=1, backupCount=7, encoding="utf-8"
        )
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    # Mark as configured
    logger._file_handler_configured = True


class SubtitleInfo:
    """Information about a subtitle file"""

    def __init__(self, file_path: str):
        """Initialize subtitle information

        Args:
            file_path: Path to the subtitle file
        """
        self.file_path = file_path
        self.format = self._detect_format(file_path)
        self.encoding = self._detect_encoding(file_path)
        self.subtitle_count = 0
        self.duration = 0  # Seconds
        self.languages = []
        self.file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        self.last_modified = os.path.getmtime(file_path) if os.path.exists(file_path) else 0

        # Parse subtitle file to get more information
        self._parse_subtitle_file()

    def _detect_format(self, file_path: str) -> str:
        """Detect subtitle file format

        Args:
            file_path: Path to the subtitle file

        Returns:
            Format of the subtitle file
        """
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".srt":
            return "srt"
        elif ext == ".vtt":
            return "vtt"
        elif ext in [".ssa", ".ass"]:
            return "ass"
        elif ext == ".sub":
            return "sub"
        else:
            return "unknown"

    def _detect_encoding(self, file_path: str) -> str:
        """Detect file encoding

        Args:
            file_path: Path to the file

        Returns:
            Detected encoding
        """
        try:
            with open(file_path, "rb") as f:
                # Read up to 16KB for better detection of files with late CJK characters
                file_size = os.path.getsize(file_path)
                read_size = min(file_size, 16384)  # 16KB max
                raw_data = f.read(read_size)

                # Priority: Check BOM first (most reliable)
                if raw_data.startswith(b"\xef\xbb\xbf"):
                    return "utf-8-sig"
                elif raw_data.startswith(b"\xff\xfe"):
                    return "utf-16-le"
                elif raw_data.startswith(b"\xfe\xff"):
                    return "utf-16-be"

                # Use chardet for detection
                result = chardet.detect(raw_data)
                encoding = result["encoding"] or "utf-8"
                confidence = result["confidence"]

                # Warn if confidence is low
                if confidence < 0.7:
                    logger.warning(f"Low encoding confidence ({confidence:.2f}) for {file_path}, using {encoding}")

                return encoding
        except Exception as e:
            logger.error(f"Error detecting file encoding: {e!s}")
            return "utf-8"  # Default to UTF-8

    def _parse_subtitle_file(self) -> None:
        """Parse subtitle file to get more information"""
        try:
            if self.format == "srt" and PYSRT_AVAILABLE:
                self._parse_srt_file()
            elif self.format == "vtt" and WEBVTT_AVAILABLE:
                self._parse_vtt_file()
            elif self.format in ["ass", "ssa"]:
                self._parse_ass_file()
            # Other formats can be added as needed
        except Exception as e:
            logger.error(f"Error parsing subtitle file: {e!s}")

    def _parse_srt_file(self) -> None:
        """Parse SRT file"""
        try:
            subs = pysrt.open(self.file_path, encoding=self.encoding)
            self.subtitle_count = len(subs)

            # Calculate total duration
            if self.subtitle_count > 0:
                try:
                    last_sub = subs[-1]
                    self.duration = last_sub.end.ordinal / 1000  # Convert to seconds
                except Exception as e:
                    logger.warning(f"Error calculating SRT duration: {e!s}")

            # Try to detect language
            self._detect_language_from_content(subs)
        except Exception as e:
            logger.error(f"Error parsing SRT file: {e!s}")

    def _parse_vtt_file(self) -> None:
        """Parse VTT file"""
        try:
            vtt = webvtt.read(self.file_path)
            self.subtitle_count = len(vtt)

            # Calculate total duration
            if self.subtitle_count > 0:
                try:
                    last_caption = vtt.captions[-1]
                    # WebVTT time format is HH:MM:SS.mmm
                    end_time = last_caption.end_in_seconds
                    self.duration = end_time
                except Exception as e:
                    logger.warning(f"Error calculating VTT duration: {e!s}")

            # Try to detect language
            content = "\n".join([caption.text for caption in vtt])
            self._detect_language_from_text(content)
        except Exception as e:
            logger.error(f"Error parsing VTT file: {e!s}")

    def _parse_ass_file(self) -> None:
        """Parse ASS/SSA file"""
        try:
            with open(self.file_path, encoding=self.encoding, errors="replace") as f:
                content = f.read()

            # Use regular expressions to extract subtitle dialogues
            dialogue_pattern = re.compile(r"Dialogue: [^,]*,([^,]*),([^,]*),")
            matches = dialogue_pattern.findall(content)

            self.subtitle_count = len(matches)

            # Calculate total duration
            if matches:
                # Try to parse the end time from the last dialogue
                try:
                    last_end_time = matches[-1][1]  # Format is usually 0:00:00.00
                    h, m, s = last_end_time.split(":")
                    self.duration = int(h) * 3600 + int(m) * 60 + float(s)
                except Exception as e:
                    logger.warning(f"Error calculating ASS duration: {e!s}")

            # Try to detect language
            self._detect_language_from_text(content)
        except Exception as e:
            logger.error(f"Error parsing ASS file: {e!s}")

    def _detect_language_from_content(self, subs) -> None:
        """Detect language from subtitle content

        Args:
            subs: Subtitle content
        """
        if self.subtitle_count == 0:
            return

        try:
            # Join some subtitle text for language detection
            sample_size = min(10, self.subtitle_count)
            sample_text = "\n".join([subs[i].text for i in range(sample_size)])
            self._detect_language_from_text(sample_text)
        except Exception as e:
            logger.warning(f"Error detecting language from subtitle content: {e!s}")

    def _detect_language_from_text(self, text: str) -> None:
        """Detect language from text

        Args:
            text: Text to detect language from
        """
        if not text:
            return

        # Language detection based on character distribution
        # Check for common language features

        # Japanese characters
        japanese_chars = len(re.findall(r"[\u3040-\u309F\u30A0-\u30FF]", text))

        # Chinese characters
        chinese_chars = len(re.findall(r"[\u4E00-\u9FFF]", text))

        # Korean characters
        korean_chars = len(re.findall(r"[\uAC00-\uD7A3]", text))

        # English and other Latin languages
        latin_chars = len(re.findall(r"[a-zA-Z]", text))

        # Count total characters (excluding whitespace)
        total_chars = len(re.sub(r"\s", "", text))
        if total_chars == 0:
            return

        # Calculate language ratios
        jp_ratio = japanese_chars / total_chars
        cn_ratio = chinese_chars / total_chars
        kr_ratio = korean_chars / total_chars
        latin_ratio = latin_chars / total_chars

        # Determine language based on ratios
        if jp_ratio > 0.3:
            self.languages.append("日文")
        if cn_ratio > 0.3:
            self.languages.append("中文")
        if kr_ratio > 0.3:
            self.languages.append("韓文")
        if latin_ratio > 0.5:
            self.languages.append("英文")

        # If no language detected, mark as unknown
        if not self.languages:
            self.languages.append("未知")

    def get_summary(self) -> Dict[str, Any]:
        """Get subtitle file summary information

        Returns:
            Summary information dictionary
        """
        return {
            "檔案路徑": self.file_path,
            "檔案名稱": os.path.basename(self.file_path),
            "格式": self.format.upper(),
            "編碼": self.encoding,
            "字幕數量": self.subtitle_count,
            "時長": self._format_duration(self.duration),
            "檔案大小": self._format_size(self.file_size),
            "語言": ", ".join(self.languages) if self.languages else "未知",
            "最後修改": datetime.fromtimestamp(self.last_modified).strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _format_duration(self, seconds: float) -> str:
        """Format time as hours:minutes:seconds

        Args:
            seconds: Time in seconds

        Returns:
            Formatted time string
        """
        if seconds <= 0:
            return "未知"

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            return f"{hours}時{minutes}分{secs}秒"
        else:
            return f"{minutes}分{secs}秒"

    def _format_size(self, size_bytes: int) -> str:
        """Format file size

        Args:
            size_bytes: Size in bytes

        Returns:
            Formatted size string
        """
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"


class FileHandler:
    """File handler for subtitle translation"""

    # Class variables for singleton pattern
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, root: Optional[tk.Tk] = None, config_section: str = "file") -> "FileHandler":
        """Get file handler singleton instance

        Args:
            root: Tkinter root window
            config_section: Configuration section to use

        Returns:
            FileHandler instance
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = FileHandler(root, config_section)
            elif root is not None:
                # Update root if provided
                cls._instance.root = root

            return cls._instance

    def __init__(self, root: Optional[tk.Tk] = None, config_section: str = "file"):
        """Initialize file handler

        Args:
            root: Tkinter root window
            config_section: Configuration section to use

        Raises:
            RuntimeError: If attempting direct instantiation when singleton exists
        """
        # Prevent direct instantiation when singleton already exists
        if self.__class__._instance is not None and self.__class__._instance is not self:
            raise RuntimeError("Use FileHandler.get_instance() instead of direct instantiation")

        self.root = root
        self.config_section = config_section

        # Get configuration manager
        self.config_manager = ConfigManager.get_instance(config_section)

        # Language suffix mapping
        self.lang_suffix = self.config_manager.get_value(
            "lang_suffix",
            {
                "繁體中文": ".zh_tw",
                "英文": ".en",
                "日文": ".jp",
                "韓文": ".kr",
                "法文": ".fr",
                "德文": ".de",
                "西班牙文": ".es",
                "俄文": ".ru",
            },
        )

        # Supported subtitle formats
        self.supported_formats = self.config_manager.get_value(
            "supported_formats",
            [
                (".srt", "SRT subtitle file"),
                (".vtt", "WebVTT subtitle file"),
                (".ass", "ASS subtitle file"),
                (".ssa", "SSA subtitle file"),
                (".sub", "SUB subtitle file"),
            ],
        )

        # Cache for subtitle file information
        self.subtitle_info_cache = {}

        # Remember last used directory
        self.last_directory = self.config_manager.get_value("last_directory", "")

        # Batch settings
        self.batch_settings = self.config_manager.get_value(
            "batch_settings",
            {
                "name_pattern": "{filename}_{language}{ext}",
                "overwrite_mode": "ask",  # ask, overwrite, rename, skip
                "output_directory": "",
                "preserve_folder_structure": True,
            },
        )

        # Thread lock for thread safety
        self._lock = threading.RLock()

        logger.debug("FileHandler initialized")

    def add_language_suffix(self, language: str, suffix: str) -> None:
        """Add or update language suffix mapping

        Args:
            language: Language name
            suffix: File suffix to use
        """
        with self._lock:
            self.lang_suffix[language] = suffix
            self.config_manager.set_value("lang_suffix", self.lang_suffix)
            logger.debug(f"Added language suffix mapping: {language} -> {suffix}")

    def select_files(self) -> List[str]:
        """Select files via dialog

        Returns:
            List of selected file paths
        """
        initial_dir = (
            self.last_directory
            if self.last_directory and os.path.exists(self.last_directory)
            else os.path.expanduser("~")
        )

        # Build filetypes filter
        filetypes = []
        for ext, desc in self.supported_formats:
            filetypes.append((desc, f"*{ext}"))
        filetypes.append(("All supported subtitle files", " ".join([f"*{ext}" for ext, _ in self.supported_formats])))
        filetypes.append(("All files", "*.*"))

        try:
            files = filedialog.askopenfilenames(
                title="Select subtitle files", initialdir=initial_dir, filetypes=filetypes
            )

            if files:
                # Update last used directory
                self.last_directory = os.path.dirname(files[0])
                self._save_last_directory()

                # Filter unsupported file formats
                valid_files = []
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if any(ext == supported_ext for supported_ext, _ in self.supported_formats):
                        valid_files.append(file)
                    else:
                        logger.warning(f"Unsupported file format: {file}")

                logger.info(f"Selected {len(valid_files)}/{len(files)} valid files")
                return valid_files
        except Exception as e:
            logger.error(f"Error selecting files: {format_exception(e)}")
            if self.root:
                messagebox.showerror("Error", f"Error selecting files: {e!s}")

        return []

    def _save_last_directory(self) -> None:
        """Save last directory to configuration"""
        with self._lock:
            self.config_manager.set_value("last_directory", self.last_directory)

    def select_directory(self) -> str:
        """Select directory

        Returns:
            Selected directory path
        """
        initial_dir = (
            self.batch_settings["output_directory"]
            if os.path.exists(self.batch_settings["output_directory"])
            else self.last_directory
        )
        if not os.path.exists(initial_dir):
            initial_dir = os.path.expanduser("~")

        try:
            directory = filedialog.askdirectory(title="Select output directory", initialdir=initial_dir)

            if directory:
                with self._lock:
                    self.batch_settings["output_directory"] = directory
                    self.config_manager.set_value("batch_settings", self.batch_settings)

                logger.info(f"Selected output directory: {directory}")
                return directory
        except Exception as e:
            logger.error(f"Error selecting directory: {format_exception(e)}")
            if self.root:
                messagebox.showerror("Error", f"Error selecting directory: {e!s}")

        return ""

    def handle_drop(self, event) -> List[str]:
        """Handle file drop event

        Args:
            event: Drop event

        Returns:
            List of valid file paths
        """
        if not TKDND_AVAILABLE or not self.root:
            logger.warning("Drag and drop functionality is not available")
            return []

        try:
            files = self.root.tk.splitlist(event.data)
            valid_files = []

            for file in files:
                # Remove braces from file paths on Windows
                file = file.strip("{}")

                # Check if it's a directory
                if os.path.isdir(file):
                    # Scan directory for subtitle files
                    logger.info(f"Directory dropped: {file}, scanning for subtitle files...")
                    dir_files = self.scan_directory(file)
                    valid_files.extend(dir_files)
                    logger.info(f"Found {len(dir_files)} subtitle files in directory {file}")
                elif os.path.isfile(file):
                    # Check file type
                    ext = os.path.splitext(file)[1].lower()
                    if any(ext == supported_ext for supported_ext, _ in self.supported_formats):
                        valid_files.append(file)
                    else:
                        logger.warning(f"Unsupported file format: {file}")
                        if self.root:
                            messagebox.showwarning(
                                "Warning",
                                f"File {os.path.basename(file)} is not a supported subtitle format and will be skipped",
                            )
                else:
                    logger.warning(f"Dropped item is not a valid file or directory: {file}")

            # Update last used directory (if valid files were found)
            if valid_files:
                self.last_directory = os.path.dirname(valid_files[0])
                self._save_last_directory()

            return valid_files

        except Exception as e:
            logger.error(f"Error handling dropped files: {format_exception(e)}")
            return []

    def scan_directory(self, directory: str, recursive: bool = True) -> List[str]:
        """Scan directory for subtitle files

        Args:
            directory: Directory path
            recursive: Whether to scan subdirectories recursively

        Returns:
            List of subtitle file paths
        """
        valid_files = []
        valid_extensions = [ext for ext, _ in self.supported_formats]

        try:
            if recursive:
                # Recursive scan
                for root, _, files in os.walk(directory):
                    for file in files:
                        ext = os.path.splitext(file)[1].lower()
                        if ext in valid_extensions:
                            valid_files.append(os.path.join(root, file))
            else:
                # Only scan current directory
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if entry.is_file():
                            ext = os.path.splitext(entry.name)[1].lower()
                            if ext in valid_extensions:
                                valid_files.append(entry.path)
        except Exception as e:
            logger.error(f"Error scanning directory: {format_exception(e)}")
            raise FileError(f"Error scanning directory: {e!s}") from e

        return valid_files

    def get_subtitle_info(self, file_path: str, force_refresh: bool = False) -> Dict[str, Any]:
        """Get subtitle file information

        Args:
            file_path: File path
            force_refresh: Whether to force refresh the cached information

        Returns:
            Subtitle information dictionary
        """
        if not os.path.exists(file_path):
            logger.warning(f"File does not exist: {file_path}")
            return {"error": "File does not exist"}

        with self._lock:
            # Check cache
            if not force_refresh and file_path in self.subtitle_info_cache:
                return self.subtitle_info_cache[file_path].get_summary()

            try:
                info = SubtitleInfo(file_path)
                # Update cache
                self.subtitle_info_cache[file_path] = info
                return info.get_summary()
            except Exception as e:
                logger.error(f"Error getting subtitle information: {format_exception(e)}")
                return {"error": f"Processing error: {e!s}"}

    def set_batch_settings(self, settings: Dict[str, Any]) -> None:
        """Set batch processing settings

        Args:
            settings: Settings dictionary
        """
        with self._lock:
            if settings:
                self.batch_settings.update(settings)
                self.config_manager.set_value("batch_settings", self.batch_settings)
                logger.debug(f"Updated batch settings: {self.batch_settings}")

    def get_output_path(self, file_path: str, target_lang: str, progress_callback=None) -> Optional[str]:
        """Get output file path and handle conflicts

        Args:
            file_path: Source file path
            target_lang: Target language
            progress_callback: Progress callback function

        Returns:
            Output file path, or None if failed
        """
        try:
            # Check if file exists
            if not os.path.exists(file_path):
                logger.warning(f"Source file does not exist: {file_path}")
                return None

            dir_name, file_name = os.path.split(file_path)
            name, ext = os.path.splitext(file_name)

            # Apply output directory from batch settings
            output_dir = self.batch_settings["output_directory"]
            if output_dir and os.path.exists(output_dir):
                # Whether to preserve directory structure
                if self.batch_settings["preserve_folder_structure"]:
                    # Get relative path (if there's a common base directory)
                    try:
                        common_base = os.path.commonpath([self.last_directory, file_path])
                        rel_dir = os.path.dirname(os.path.relpath(file_path, common_base))
                        new_dir = os.path.join(output_dir, rel_dir)

                        # Security check: use pathlib for robust path traversal prevention
                        if not self._is_path_within_directory(new_dir, output_dir):
                            logger.warning(
                                f"Path traversal attempt blocked: {new_dir} is not within {output_dir}, "
                                "using flat structure"
                            )
                            new_dir = output_dir
                        else:
                            os.makedirs(new_dir, exist_ok=True)
                    except Exception as e:
                        logger.warning(f"Error calculating relative path: {e!s}, using flat structure")
                        new_dir = output_dir
                else:
                    new_dir = output_dir

                dir_name = new_dir

            # Get language suffix
            lang_suffix = self.lang_suffix.get(target_lang, ".unknown")

            # Apply file naming pattern
            name_pattern = self.batch_settings["name_pattern"]
            output_filename = name_pattern.format(
                filename=name,
                language=target_lang.lower(),
                suffix=lang_suffix.replace(".", ""),
                ext=ext,
                date=datetime.now().strftime("%Y%m%d"),
                time=datetime.now().strftime("%H%M%S"),
            )

            # If output filename doesn't have an extension, add the original extension
            if not os.path.splitext(output_filename)[1]:
                output_filename += ext

            base_path = os.path.join(dir_name, output_filename)

            # Handle file conflicts
            if os.path.exists(base_path):
                # Check conflict handling mode
                overwrite_mode = self.batch_settings["overwrite_mode"]

                if overwrite_mode == "ask" and progress_callback:
                    # Ask user via callback function
                    queue = Queue()
                    progress_callback(-1, -1, {"type": "file_conflict", "path": base_path, "queue": queue})
                    response = queue.get()

                    if response == "rename":
                        return self._get_unique_path(dir_name, name, lang_suffix, ext)
                    elif response == "skip":
                        return None
                    # "overwrite" case will just return base_path

                elif overwrite_mode == "rename":
                    # Automatically rename
                    return self._get_unique_path(dir_name, name, lang_suffix, ext)

                elif overwrite_mode == "skip":
                    # Skip existing files
                    logger.info(f"File already exists, skipping: {base_path}")
                    return None

                # "overwrite" case will just return base_path

            # 規範化路徑，確保路徑分隔符統一（Windows 環境下避免混用 / 和 \\）
            return os.path.normpath(base_path)
        except Exception as e:
            logger.error(f"Error getting output path: {format_exception(e)}")
            raise FileError(f"Error determining output path: {e!s}") from e

    def _is_path_within_directory(self, path: str, directory: str) -> bool:
        """Check if a path is safely within a directory (path traversal prevention)

        Uses pathlib.Path.relative_to() for robust path comparison that handles
        edge cases like symbolic links, case sensitivity, and path separators.

        Args:
            path: The path to check
            directory: The base directory that path should be within

        Returns:
            True if path is within directory, False otherwise
        """
        try:
            # Resolve both paths to absolute, normalized form
            path_resolved = Path(path).resolve()
            directory_resolved = Path(directory).resolve()

            # relative_to() raises ValueError if path is not relative to directory
            path_resolved.relative_to(directory_resolved)
            return True
        except ValueError:
            # Path is not within directory
            return False
        except OSError as e:
            # Handle filesystem errors (e.g., invalid paths)
            logger.warning(f"Error checking path relationship: {e}")
            return False

    def _get_unique_path(self, dir_name: str, name: str, lang_suffix: str, ext: str) -> str:
        """Get unique file path (to avoid conflicts)

        Args:
            dir_name: Directory path
            name: Base file name
            lang_suffix: Language suffix
            ext: File extension

        Returns:
            Unique file path
        """
        counter = 1
        while True:
            new_path = os.path.join(dir_name, f"{name}{lang_suffix}_{counter}{ext}")
            # 規範化路徑，確保路徑分隔符統一
            new_path = os.path.normpath(new_path)
            if not os.path.exists(new_path):
                return new_path
            counter += 1

    def load_api_key(self, file_path: str = "openapi_api_key.txt") -> str:
        """Load API key

        Args:
            file_path: API key file path

        Returns:
            API key string

        Note:
            Environment variables are the recommended way to store API keys.
            File-based storage is deprecated and will show a security warning.
        """
        try:
            # Try to read from environment variable (recommended)
            api_key = os.environ.get("OPENAI_API_KEY")
            if api_key:
                logger.info("Loaded API key from environment variable")
                return api_key

            # Try to read from file (deprecated, with security warning)
            if os.path.exists(file_path):
                logger.warning(
                    f"Loading API key from file '{file_path}' is insecure. "
                    "Please use environment variable OPENAI_API_KEY instead."
                )
                with open(file_path, encoding="utf-8") as f:
                    api_key = f.read().strip()

                if api_key:
                    logger.info(f"Loaded API key from file {file_path}")
                    return api_key

            logger.warning(f"API key file {file_path} does not exist or is empty")
            return ""
        except Exception as e:
            logger.error(f"Error reading API key: {format_exception(e)}")
            return ""

    def save_api_key(self, api_key: str, file_path: str = "openapi_api_key.txt") -> bool:
        """Save API key to file (DEPRECATED - use environment variables instead)

        .. deprecated::
            Storing API keys in plaintext files is insecure.
            Use environment variables (OPENAI_API_KEY) instead.

        Args:
            api_key: API key string
            file_path: Output file path

        Returns:
            Whether the operation was successful

        Warning:
            This method stores API keys in plaintext which is a security risk.
            The file will be created with restricted permissions where supported.
        """
        import stat
        import warnings

        # Issue deprecation warning
        warnings.warn(
            "save_api_key() is deprecated and insecure. Use environment variable OPENAI_API_KEY instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        logger.warning(
            "Saving API key to file is deprecated and insecure. Please use environment variable OPENAI_API_KEY instead."
        )

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(api_key)

            # Set restrictive file permissions (owner read/write only)
            # This only works on Unix-like systems; on Windows it's a no-op
            try:
                os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
                logger.debug(f"Set restrictive permissions on {file_path}")
            except OSError as perm_error:
                # On Windows, chmod may not work as expected
                logger.warning(
                    f"Could not set restrictive file permissions: {perm_error}. "
                    "On Windows, please manually restrict access to this file."
                )

            logger.info(f"Saved API key to file: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving API key: {format_exception(e)}")
            return False

    def convert_subtitle_format(self, input_path: str, target_format: str) -> Optional[str]:
        """Convert subtitle file format

        Args:
            input_path: Input file path
            target_format: Target format (without dot)

        Returns:
            Output file path, or None if failed
        """
        try:
            # Check source file
            if not os.path.exists(input_path):
                logger.warning(f"Source file does not exist: {input_path}")
                return None

            # Check source and target formats
            source_format = os.path.splitext(input_path)[1].lower().replace(".", "")
            if source_format == target_format:
                logger.info(f"Source file is already in {target_format} format: {input_path}")
                return input_path

            # Get output file path
            output_dir = os.path.dirname(input_path)
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            output_path = os.path.join(output_dir, f"{base_name}.{target_format}")

            # Ensure output path is not the same as source path
            if output_path == input_path:
                output_path = os.path.join(output_dir, f"{base_name}_converted.{target_format}")

            # Handle file already exists case
            if os.path.exists(output_path):
                output_path = self._get_unique_path(output_dir, base_name, "_converted", f".{target_format}")

            # Convert between different formats
            if source_format == "srt" and target_format == "vtt":
                self._convert_srt_to_vtt(input_path, output_path)
            elif source_format == "vtt" and target_format == "srt":
                self._convert_vtt_to_srt(input_path, output_path)
            # More format conversions can be added here
            else:
                logger.warning(f"Conversion from {source_format} to {target_format} is not supported yet")
                return None

            logger.info(f"Converted {input_path} to {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Error converting subtitle format: {format_exception(e)}")
            raise FileError(f"Error converting subtitle format: {e!s}") from e

    def _convert_srt_to_vtt(self, srt_path: str, vtt_path: str) -> None:
        """Convert SRT format to VTT format

        Args:
            srt_path: SRT file path
            vtt_path: VTT file path
        """
        if not PYSRT_AVAILABLE:
            raise ImportError("pysrt package is missing, cannot convert SRT format")

        # Read SRT file
        encoding = self.get_subtitle_info(srt_path).get("編碼", "utf-8")
        subs = pysrt.open(srt_path, encoding=encoding)

        # Write VTT file
        with open(vtt_path, "w", encoding="utf-8") as f:
            f.write("WEBVTT\n\n")

            for sub in subs:
                # Convert time format (00:00:00,000 -> 00:00:00.000)
                start = sub.start.to_time().strftime("%H:%M:%S.%f")[:-3]
                end = sub.end.to_time().strftime("%H:%M:%S.%f")[:-3]

                # Write subtitle
                f.write(f"{start} --> {end}\n")
                f.write(f"{sub.text}\n\n")

    def _convert_vtt_to_srt(self, vtt_path: str, srt_path: str) -> None:
        """Convert VTT format to SRT format

        Args:
            vtt_path: VTT file path
            srt_path: SRT file path
        """
        if not WEBVTT_AVAILABLE:
            raise ImportError("webvtt package is missing, cannot convert VTT format")

        # Read VTT file
        vtt = webvtt.read(vtt_path)

        # Write SRT file
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, caption in enumerate(vtt, 1):
                # Convert time format (00:00:00.000 -> 00:00:00,000)
                start = caption.start.replace(".", ",")
                end = caption.end.replace(".", ",")

                # Write subtitle
                f.write(f"{i}\n")
                f.write(f"{start} --> {end}\n")
                f.write(f"{caption.text}\n\n")

    def _validate_path_for_subprocess(self, path: str, must_exist: bool = False) -> bool:
        """Validate a path before using it in subprocess commands

        Args:
            path: The path to validate
            must_exist: Whether the path must exist

        Returns:
            True if the path is valid for subprocess use

        Raises:
            FileError: If the path is invalid or contains suspicious characters
        """
        if not path or not isinstance(path, str):
            raise FileError("Invalid path: path is empty or not a string")

        # Check for suspicious characters that could indicate injection attempts
        # Note: spaces and Unicode are allowed, but shell metacharacters are not
        suspicious_chars = ["|", "&", ";", "$", "`", ">", "<", "\n", "\r", "\0"]
        for char in suspicious_chars:
            if char in path:
                raise FileError(f"Path contains suspicious character: '{char}'")

        # Check if path exists when required
        if must_exist and not os.path.exists(path):
            raise FileError(f"Path does not exist: {path}")

        # Resolve and normalize the path
        try:
            resolved_path = Path(path).resolve()
            # Ensure the resolved path doesn't escape to unexpected locations
            # by checking it's under a reasonable root
            if not resolved_path.parts:
                raise FileError("Path resolves to empty location")
        except (OSError, ValueError) as e:
            raise FileError(f"Invalid path format: {e}") from e

        return True

    def extract_subtitle(self, video_path: str, callback=None) -> Optional[str]:
        """Extract subtitle from video file

        Args:
            video_path: Video file path
            callback: Callback function

        Returns:
            Subtitle file path, or None if failed

        Raises:
            FileError: If video path is invalid or extraction fails
        """
        try:
            import subprocess

            # Validate video path before any operations
            self._validate_path_for_subprocess(video_path, must_exist=True)

            if not os.path.isfile(video_path):
                raise FileError(f"Video path is not a file: {video_path}")

            # Check if ffmpeg is available
            try:
                subprocess.run(
                    ["ffmpeg", "-version"],
                    capture_output=True,
                    check=True,
                    timeout=10,  # 10 seconds timeout for version check
                )
            except subprocess.TimeoutExpired as e:
                logger.error("ffmpeg version check timed out")
                raise FileError("ffmpeg version check timed out") from e
            except (subprocess.SubprocessError, FileNotFoundError) as e:
                logger.error("ffmpeg not found, cannot extract subtitle")
                raise FileError("ffmpeg not found, cannot extract subtitle") from e

            # Prepare paths
            output_dir = os.path.dirname(video_path) or "."
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            output_path = os.path.join(output_dir, f"{base_name}.srt")

            # Ensure output path does not exist
            if os.path.exists(output_path):
                output_path = self._get_unique_path(output_dir, base_name, "_extracted", ".srt")

            # Validate output path is within expected directory
            if not self._is_path_within_directory(output_path, output_dir):
                raise FileError(f"Output path escapes expected directory: {output_path}")

            # Validate output path for subprocess use
            self._validate_path_for_subprocess(output_path, must_exist=False)

            # Extract subtitle command
            cmd = [
                "ffmpeg",
                "-i",
                video_path,
                "-map",
                "0:s:0",  # Select first subtitle track
                "-c",
                "copy",
                output_path,
            ]

            # Execute command
            if callback:
                callback(-1, -1, {"type": "extracting", "path": video_path})

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=300,  # 5 minutes timeout for subtitle extraction
                )
            except subprocess.TimeoutExpired as e:
                logger.error(f"Subtitle extraction timed out (300s): {video_path}")
                raise FileError("Subtitle extraction timed out (300 seconds)") from e

            # Check result
            if result.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                logger.warning(f"Failed to extract subtitle: {result.stderr.decode()}")
                raise FileError(f"Failed to extract subtitle: {result.stderr.decode()}")

            logger.info(f"Extracted subtitle from {video_path} to {output_path}")
            return output_path

        except ImportError as e:
            logger.error(f"Import error: {format_exception(e)}")
            raise FileError(f"Missing required package: {e!s}") from e
        except Exception as e:
            logger.error(f"Error extracting subtitle: {format_exception(e)}")
            raise FileError(f"Error extracting subtitle: {e!s}") from e

    def cleanup(self) -> None:
        """Clean up resources"""
        # For future use
        pass


# Global functions for easy access
def get_file_handler(root: Optional[tk.Tk] = None) -> FileHandler:
    """Get file handler instance

    Args:
        root: Tkinter root window

    Returns:
        FileHandler instance
    """
    return FileHandler.get_instance(root)


def select_files(root: Optional[tk.Tk] = None) -> List[str]:
    """Select subtitle files

    Args:
        root: Tkinter root window

    Returns:
        List of selected file paths
    """
    handler = get_file_handler(root)
    return handler.select_files()


def get_subtitle_info(file_path: str) -> Dict[str, Any]:
    """Get subtitle file information

    Args:
        file_path: Subtitle file path

    Returns:
        Subtitle information dictionary
    """
    handler = get_file_handler()
    return handler.get_subtitle_info(file_path)


def scan_directory(directory: str, recursive: bool = True) -> List[str]:
    """Scan directory for subtitle files

    Args:
        directory: Directory path
        recursive: Whether to scan subdirectories recursively

    Returns:
        List of subtitle file paths
    """
    handler = get_file_handler()
    return handler.scan_directory(directory, recursive)


# For testing the module
if __name__ == "__main__":
    # Setup console logging for testing
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter("%(levelname)s - %(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    print("===== File Handler Test =====")

    # Initialize tk for file dialog tests
    root = tk.Tk()
    root.withdraw()  # Hide the root window

    file_handler = FileHandler.get_instance(root)

    # Test file selection
    print("\n1. Testing file selection")
    files = file_handler.select_files()
    print(f"Selected files: {files}")

    if files:
        # Test subtitle info
        print("\n2. Testing subtitle info")
        test_file = files[0]
        info = file_handler.get_subtitle_info(test_file)
        for key, value in info.items():
            print(f"  {key}: {value}")

        # Test output path generation
        print("\n3. Testing output path generation")
        output_path = file_handler.get_output_path(test_file, "繁體中文")
        print(f"Output path: {output_path}")

        # Test format conversion
        if os.path.splitext(test_file)[1].lower() == ".srt":
            print("\n4. Testing format conversion (SRT to VTT)")
            try:
                vtt_path = file_handler.convert_subtitle_format(test_file, "vtt")
                print(f"Converted to: {vtt_path}")
            except Exception as e:
                print(f"Conversion failed: {e!s}")

    # Test batch settings
    print("\n5. Testing batch settings")
    new_settings = {"name_pattern": "{filename}_{language}_{date}{ext}", "overwrite_mode": "rename"}
    file_handler.set_batch_settings(new_settings)
    print(f"Updated batch settings: {file_handler.batch_settings}")

    print("\n===== Test Complete =====")
