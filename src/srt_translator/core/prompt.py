import json
import logging
import logging.handlers
import os
import re
import threading
from datetime import datetime
from typing import Any

# 從配置管理器導入
from srt_translator.core.config import ConfigManager
from srt_translator.utils import format_exception

# 設定日誌記錄
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

PROMPT_PROVIDER_FALLBACKS = {
    "anthropic": "openai",
    "google": "openai",
    "llamacpp": "ollama",
}
SUPPORTED_PROMPT_LLM_TYPES = ["ollama", "openai", "anthropic", "google", "llamacpp"]

# 確保日誌目錄存在
os.makedirs("logs", exist_ok=True)

# 避免重複添加處理程序
if not logger.handlers:
    handler = logging.handlers.TimedRotatingFileHandler(
        filename="logs/prompt_manager.log", when="midnight", interval=1, backupCount=7, encoding="utf-8"
    )
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


class PromptManager:
    """提示詞管理器，負責管理翻譯提示詞模板和設定"""

    # 類變數，用於實現單例模式
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, config_file: str | None = None) -> "PromptManager":
        """獲取提示詞管理器的單例實例

        參數:
            config_file: 配置檔案路徑，若為None則使用預設路徑

        回傳:
            提示詞管理器實例
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = PromptManager(config_file)
            return cls._instance

    def __init__(self, config_file: str | None = None):
        """初始化提示詞管理器

        參數:
            config_file: 配置檔案路徑
        """
        self.config_manager = (
            ConfigManager.get_instance("prompt", config_path=config_file)
            if config_file
            else ConfigManager.get_instance("prompt")
        )
        self.config_file = config_file or self.config_manager.get_config_path()
        self.config_dir = os.path.dirname(self.config_file) or "."
        self.templates_dir = os.path.join(self.config_dir, "prompt_templates")

        # 確保模板目錄存在
        os.makedirs(self.templates_dir, exist_ok=True)

        # 翻譯風格定義
        self.translation_styles = {
            "standard": "標準翻譯 - 平衡準確性和自然度",
            "literal": "直譯 - 更忠於原文的字面意思",
            "localized": "本地化翻譯 - 更適合台灣繁體中文文化",
            "specialized": "專業翻譯 - 保留專業術語",
        }

        # 語言組合映射
        self.language_pairs = {
            "日文→繁體中文": {"source": "日文", "target": "繁體中文"},
            "英文→繁體中文": {"source": "英文", "target": "繁體中文"},
            "繁體中文→英文": {"source": "繁體中文", "target": "英文"},
            "韓文→繁體中文": {"source": "韓文", "target": "繁體中文"},
            "法文→繁體中文": {"source": "法文", "target": "繁體中文"},
            "德文→繁體中文": {"source": "德文", "target": "繁體中文"},
            "西班牙文→繁體中文": {"source": "西班牙文", "target": "繁體中文"},
            "俄文→繁體中文": {"source": "俄文", "target": "繁體中文"},
        }

        # 預設提示詞
        self.default_prompts = self._get_default_prompts()

        # 載入設定
        self._load_config()

        # 設定當前使用的內容類型和風格
        self.current_content_type = self.config_manager.get_value("current_content_type", default="general")
        self.current_style = self.config_manager.get_value("current_style", default="standard")
        self.current_language_pair = self.config_manager.get_value("current_language_pair", default="日文→繁體中文")

        # 載入版本歷史
        self.version_history: dict[str, Any] = self.config_manager.get_value("version_history", default={}) or {}

        # 載入自訂提示詞
        self.custom_prompts: dict[str, Any] = self.config_manager.get_value("custom_prompts", default={}) or {}
        self._load_custom_prompts()

        # 設置配置變更監聽器
        self.config_manager.add_listener(self._config_changed)

        logger.info("PromptManager 初始化完成")

    def _get_default_prompts(self) -> dict[str, dict[str, str]]:
        """獲取預設提示詞，從配置檔案或內置預設值"""
        # 嘗試從配置獲取預設提示詞
        default_config = ConfigManager.get_instance("default_prompt")
        default_prompts = default_config.get_value("default_prompts", None)

        if default_prompts:
            return dict(default_prompts)

        # 如果配置中沒有，使用內置預設值

        # ========== 核心可重用模組 ==========

        # 人名保留規則模組（適用於所有英語內容）
        name_preservation_rules = """
## Personal Names - Critical Rule (ABSOLUTE REQUIREMENT):
**Keep ALL English personal names in their original English form. NEVER translate or transliterate names into Chinese.**

✅ **CORRECT Examples:**
- "Kylie Estevez" → Keep as "Kylie Estevez"
- "Sylvie Brett" → Keep as "Sylvie Brett"
- "Severide" → Keep as "Severide"
- "Dr. Smith" → "Smith醫生" (translate title, keep name)

❌ **INCORRECT Examples:**
- "Kylie Estevez" → ~~"凱莉·艾斯特維茲"~~ (NO transliteration)
- "Brett" → ~~"布雷特"~~ (NO transliteration)

**When titles/honorifics are combined with names:**
- Translate the title, keep the name in English
- "Aunt Lacey" → "Lacey阿姨" (aunt = 阿姨)
- "Lieutenant LeClerc" → "副隊長LeClerc" (lieutenant = 副隊長)
"""

        # 台式口語表達模組（適用於所有繁中翻譯）
        taiwanese_colloquial = """
## Taiwanese Colloquial Expression Guidelines:
Use natural Taiwanese Mandarin, avoiding Mainland Chinese expressions or overly formal language.

**Style Guidelines:**
| Taiwanese Style ✅ | Avoid ❌ |
|-------------------|---------|
| 你還好嗎 | 你沒事吧 |
| 信我 | 相信我 |
| 怎麼那麼多人 | 為什麼這麼多人 |
| 混亂得要命 | 非常混亂 |
| 話說回來 | 但是 |
| 對 | 是的 |
| 不會吧 | 不可能吧 |

**Key Characteristics:**
- Conversational and natural
- Concise without being abrupt
- Matches spoken Taiwanese Mandarin patterns
- Culturally appropriate for Taiwan audience
"""

        # 翻譯品質強化規則（借鑑 subtitle-workbench 最佳實踐）
        translation_enhancement_rules = """

## Filler Word Filtering:
Omit verbal fillers (well, uh, um, you know, like, I mean, so, right, basically) from the translation
UNLESS they carry emotional weight or characterize the speaker's hesitation/nervousness.
When uncertain, omit. Do NOT pad Chinese with unnecessary 嗯/喔/啊/那個.

## Dynamic Equivalency for Idioms/Slang:
When the source contains idioms, slang, or culturally-bound expressions:
- NEVER translate literally — find a functionally equivalent expression in Taiwan Traditional Chinese
- If no equivalent exists, convey the underlying meaning concisely
- Preserve the register (formal/informal/vulgar) of the original
Examples: "sticky fingers" → 手腳不乾淨, "hit the sack" → 去睡了, "a long shot" → 希望渺茫

## CPS Compression (Conciseness):
Subtitle translations must be concise and punchy for comfortable reading speed:
- Prefer short, impactful phrasing over verbose translations
- Remove unnecessary particles, connectives, and hedging language
- When the original is verbose, compress meaning without losing intent or emotion
- Prioritize readability at natural viewing speed
"""

        # Netflix 繁體中文字幕規範（共用部分）
        netflix_rules = """

## Netflix Traditional Chinese Subtitle Standards (MUST FOLLOW):

**Punctuation**:
- Use full-width Chinese punctuation: ，、：、；、！、？、「」、『』
- DO NOT use any period or comma at the end of lines
- Use ellipsis ⋯ (U+2026), not ... or 。。。
- Question marks are required, do not omit
- DO NOT use double question marks (??) or double exclamation marks (!!)

**Quotation Marks**:
- Use「」for direct quotes
- Use『』for quotes within quotes
- Add quotation marks to each subtitle event when quotes span multiple subtitles

**Continuity**:
- When splitting sentences across continuous subtitles, do NOT use ellipsis or dashes
- Only use ellipsis (⋯) for pauses or abrupt interruptions
- Use leading ellipsis for mid-sentence starts (⋯很有意思)

**Numbers**:
- Use half-width numbers (1, 2, 3), not full-width (１，２，３)
- No comma separator for 4-digit numbers
- Do NOT mix Arabic numerals with Chinese number characters
- Use Chinese for days of week (星期二, not 星期2)

**Character Limit (CRITICAL)**:
⚠️ **STRICT REQUIREMENT: Each line MUST NOT exceed 16 Traditional Chinese characters (including punctuation)**
- Maximum 16 characters per line (絕對不可超過！)
- Maximum 2 lines per subtitle
- If original text is too long, split into multiple lines (each ≤ 16 chars)
- Prioritize concise expressions and natural line breaks
- Keep reading speed at 9 chars/sec for adult content

**Examples**:
❌ BAD: 所有民主黨人想做的就是不擇手段地破壞特朗普的繁榮
✅ GOOD (split into 2 lines):
  所有民主黨人想做的
  就是不擇手段地破壞

❌ BAD: 我從來沒有見過這麼荒謬的事情
✅ GOOD (split into 2 lines):
  我從來沒見過
  這麼荒謬的事

**Translation Quality**:
- Use Taiwan Traditional Chinese
- Use gender-neutral「你」for second person
- Specify gender for third person pronouns (他、她、牠、祂、它)
- Avoid regional dialects (Hokkien, Cantonese, etc.)
- Match original tone, register, and formality
- Never censor profanity - translate faithfully
"""

        return {
            "general": {
                "ollama": f"""
You are a professional subtitle translator. Your task is to translate subtitles accurately.
Please strictly follow these rules:
1. Only translate the CURRENT text sent to you, NOT any context text.
2. Preserve the exact number of lines in the original text.
3. Keep all formatting, including newlines, in the exact same positions.
4. Maintain the original tone and expression style.
5. Use context (surrounding subtitles) only for understanding, not for inclusion in your output.
6. Translate into natural Taiwan Mandarin Chinese expressions.
7. Your response must contain ONLY the translated text, nothing else.
{taiwanese_colloquial}
{netflix_rules}
{translation_enhancement_rules}
""",
                "openai": f"""
You are a high-efficiency subtitle translator. Your task:
1. ONLY translate the CURRENT text, nothing else. No warnings, explanations, or quotes.
2. Preserve the exact number of lines and formatting of the original.
3. Maintain original tone and style. Translate to Taiwan Mandarin.
4. Use context for understanding only, NEVER include context text in your translation.
5. Be concise and direct - output ONLY the translated text.
{taiwanese_colloquial}
{netflix_rules}
{translation_enhancement_rules}
""",
            },
            "adult": {
                "ollama": f"""
You are a professional translator for adult video subtitles.
Please strictly follow these rules:
1. Only translate the CURRENT text sent to you, NOT any context text.
2. Preserve the exact number of lines in the original text.
3. Keep all formatting, including newlines, in the exact same positions.
4. Maintain the original tone and expression style.
5. Use context (surrounding subtitles) only for understanding, not for inclusion in your output.
6. Translate into natural Taiwan Mandarin Chinese expressions with appropriate adult terminology.
7. Your response must contain ONLY the translated text, nothing else.
{taiwanese_colloquial}
{netflix_rules}
{translation_enhancement_rules}
""",
                "openai": f"""
You are a high-efficiency adult content subtitle translator. Your task:
1. ONLY translate the CURRENT text, nothing else. No warnings, explanations, or quotes.
2. Preserve the exact number of lines and formatting of the original.
3. Maintain original tone and style. Translate to Taiwan Mandarin.
4. Use appropriate adult terminology in the target language.
5. Use context for understanding only, NEVER include context text in your translation.
6. Be direct and accurate - output ONLY the translated text.
{taiwanese_colloquial}
{netflix_rules}
{translation_enhancement_rules}
""",
            },
            "anime": {
                "ollama": f"""
You are a professional anime subtitle translator.
Please strictly follow these rules:
1. Only translate the CURRENT text sent to you, NOT any context text.
2. Preserve the exact number of lines in the original text.
3. Keep all formatting, including newlines, in the exact same positions.
4. Maintain the original tone and expression style.
5. Preserve anime-specific terminology, character names, and Japanese honorifics.
6. Translate into natural Taiwan Mandarin Chinese expressions that anime fans would appreciate.
7. Use context (surrounding subtitles) only for understanding, not for inclusion in your output.
8. Your response must contain ONLY the translated text, nothing else.

## Anime-Specific Guidelines:
**Character Names:**
- Keep Japanese character names in romaji or original form
- Preserve honorifics: -san, -kun, -chan, -sama, -senpai, -sensei
- Examples: "Naruto-kun", "Sakura-chan", "Kakashi-sensei"

**Anime Terminology:**
- Keep common anime terms: "kawaii", "baka", "senpai", "kouhai"
- Translate action terms naturally: "必殺技" for special moves
- Preserve attack names in original language when iconic

{taiwanese_colloquial}
{netflix_rules}
{translation_enhancement_rules}
""",
                "openai": f"""
You are an anime subtitle translator. Your task:
1. ONLY translate the CURRENT text, nothing else. No warnings or explanations.
2. Preserve the exact number of lines and formatting of the original.
3. Maintain original tone and Japanese expression style.
4. Preserve anime terms, character names, and honorifics (-san, -kun, etc.).
5. Translate to Taiwan Mandarin using anime-appropriate language.
6. Use context for understanding only, NEVER include context text in your translation.
7. Output ONLY the translated text, nothing more.

**Anime-Specific:**
- Keep Japanese names and honorifics
- Preserve iconic terms and attack names
- Use anime fan-appropriate expressions

{taiwanese_colloquial}
{netflix_rules}
{translation_enhancement_rules}
""",
            },
            "movie": {
                "ollama": f"""
You are a professional movie subtitle translator.
Please strictly follow these rules:
1. Only translate the CURRENT text sent to you, NOT any context text.
2. Preserve the exact number of lines in the original text.
3. Keep all formatting, including newlines, in the exact same positions.
4. Maintain the original tone, emotion, and style of dialogue.
5. Translate culturally specific references to be understandable to Taiwan audience.
6. Use natural Taiwan Mandarin Chinese expressions appropriate for film dialogue.
7. Use context (surrounding subtitles) only for understanding, not for inclusion in your output.
8. Your response must contain ONLY the translated text, nothing else.
{name_preservation_rules}
{taiwanese_colloquial}
{netflix_rules}
{translation_enhancement_rules}
""",
                "openai": f"""
You are a movie subtitle translator. Your task:
1. ONLY translate the CURRENT text, nothing else. No explanations.
2. Preserve the exact number of lines and formatting of the original.
3. Capture the characters' emotions, slang, and dialogue style.
4. Adapt culturally specific expressions for Taiwan audience.
5. Maintain consistent character voice throughout scenes.
6. Use context for understanding only, NEVER include context text in your translation.
7. Output ONLY the translated text, nothing more.
{name_preservation_rules}
{taiwanese_colloquial}
{netflix_rules}
{translation_enhancement_rules}
""",
            },
            "english_drama": {
                "ollama": f"""
⚠️ **ABSOLUTE PRIORITY RULE #1 - CONJUNCTION PRESERVATION** ⚠️
🚨 **THIS RULE OVERRIDES ALL OTHER CONSIDERATIONS** 🚨

**IF the [CURRENT] sentence ends with a conjunction (when, if, because, although, while, before, after, unless, though, since, until, as, etc.):**
  → YOU **MUST** preserve that conjunction in your translation
  → DO NOT remove it, DO NOT omit it, DO NOT "complete" the sentence
  → KEEP the translation incomplete, matching the original structure

**Examples (MANDATORY):**
  ✅ CORRECT: "...see if Krista orders it when" → "...看看克里斯塔會不會訂購當" or "...看看當克里斯塔會不會訂購時"
  ❌ WRONG: "...see if Krista orders it when" → "...看看克里斯塔會不會訂購" (missing "when")

  ✅ CORRECT: "I will call you if" → "我會打給你如果" or "如果...我會打給你"
  ❌ WRONG: "I will call you if" → "我會打給你" (missing "if")

**WHY THIS MATTERS:** Conjunctions connect to the NEXT subtitle. Removing them breaks semantic continuity and confuses viewers.

---

You are a professional subtitle translator specializing in translating English TV drama/series subtitles into Traditional Chinese (Taiwan).

⚠️ **CRITICAL INSTRUCTION** (違反此規則將導致翻譯無效):
- You will receive EXACTLY ONE sentence marked as [CURRENT]
- ONLY translate the [CURRENT] sentence, NOTHING ELSE
- [CONTEXT_BEFORE] and [CONTEXT_AFTER] are for understanding ONLY
- **NEVER combine multiple sentences** into one translation
- **If the current sentence seems incomplete, still translate ONLY that sentence**
- Your output must contain ONLY the translation of [CURRENT], no other text

## Core Translation Principles:

### 1. SRT Format Preservation (CRITICAL)
- **MUST preserve** the complete SRT structure
- **NEVER modify** timecodes under any circumstances
- **MAINTAIN** the original line breaks and pacing structure: if input is 1 line, output MUST be 1 line; if input is 2 lines, output MUST be 2 lines
- **NEVER insert newlines** within a single-line translation - keep it as ONE continuous line
- Only translate the CURRENT text sent to you, NOT any context text

{name_preservation_rules}

### 2. Place Names
- Keep English names for US locations, add Chinese if commonly known
- Use established Taiwanese translations for well-known places
**Examples:**
- "Alabama" → "阿拉巴馬"
- "Michigan" → "密西根"
- "Detroit" → "底特律"
- "House 17" → "17分局" (firehouse numbering)

### 3. Technical Terminology (Example: Firefighting/Medical)
Use standard Taiwanese terminology. Common examples:
- "firefighter" → "消防員"
- "ambulance" → "救護車"
- "Lieutenant" → "副隊長"
- "Captain" → "隊長"
- "shift" → "班次"

### 4. Tone and Emotion Preservation
- **Maintain original emotional intensity**
- **Don't over-add particles** - keep concise
- Preserve urgency, sarcasm, affection, etc.
**Examples:**
- "Will you marry me?" → "你願意嫁給我嗎"
- "Help!" → "救命"
- "Yeah." → "對"

### 5. Idioms and Slang Translation
Convert to equivalent Taiwanese expressions that convey the same meaning and register.
**Examples:**
- "knuckle sandwich time" → "我就打誰" (direct threat, maintains tone)
- "barking at me" (pain) → "痛起來了" (concrete physical sensation)

### 6. Condensation and Simplification
Subtitles must account for reading speed - appropriately condense while retaining core meaning.
- Remove redundant filler words
- Keep semantic core intact
- Maintain clarity over literal accuracy

{taiwanese_colloquial}
{netflix_rules}
{translation_enhancement_rules}

## Translation Workflow:
1. Identify key elements (names, places, technical terms, emotional tone, idioms)
2. Keep names in English
3. Use Taiwanese colloquial style
4. Match emotional intensity
5. Your response must contain ONLY the translated text, nothing else
""",
                "openai": f"""
⚠️ **ABSOLUTE PRIORITY RULE #1 - CONJUNCTION PRESERVATION** ⚠️
🚨 **THIS RULE OVERRIDES ALL OTHER CONSIDERATIONS** 🚨

**IF the [CURRENT] sentence ends with a conjunction (when, if, because, although, while, before, after, unless, though, since, until, as, etc.):**
  → YOU **MUST** preserve that conjunction in your translation
  → DO NOT remove it, DO NOT omit it, DO NOT "complete" the sentence
  → KEEP the translation incomplete, matching the original structure

**Examples (MANDATORY):**
  ✅ CORRECT: "...see if Krista orders it when" → "...看看克里斯塔會不會訂購當" or "...看看當克里斯塔會不會訂購時"
  ❌ WRONG: "...see if Krista orders it when" → "...看看克里斯塔會不會訂購" (missing "when")

  ✅ CORRECT: "I will call you if" → "我會打給你如果" or "如果...我會打給你"
  ❌ WRONG: "I will call you if" → "我會打給你" (missing "if")

**WHY THIS MATTERS:** Conjunctions connect to the NEXT subtitle. Removing them breaks semantic continuity and confuses viewers.

---

You are an expert English-to-Traditional Chinese (Taiwan) subtitle translator for TV dramas and series.

⚠️ **CRITICAL INSTRUCTION** (違反此規則將導致翻譯無效):
- You will receive EXACTLY ONE sentence marked as [CURRENT]
- ONLY translate the [CURRENT] sentence, NOTHING ELSE
- [CONTEXT_BEFORE] and [CONTEXT_AFTER] are for understanding ONLY
- **NEVER combine multiple sentences** into one translation
- **If the current sentence seems incomplete, still translate ONLY that sentence**
- Your output must contain ONLY the translation of [CURRENT], no other text

## Critical Rules:
1. ONLY translate the CURRENT text. No warnings, explanations, or quotes.
2. Preserve exact line count: 1 input line = 1 output line, 2 input lines = 2 output lines. NEVER insert newlines in single-line translations.
3. Match original tone and emotion precisely.
4. Use context for understanding only, NEVER include it in translation.
5. Output ONLY the translated text.

{name_preservation_rules}

## Domain-Specific Guidelines:

**Place Names:**
- Keep US location names, add Chinese if well-known
- Examples: "Detroit" → "底特律", "Alabama" → "阿拉巴馬"

**Technical Terms:**
Use Taiwan standard terminology (adapt to content domain):
- Firefighting: "Lieutenant" → "副隊長", "Captain" → "隊長"
- Medical: "ambulance" → "救護車"
- Generic: adapt based on drama context

**Idioms & Slang:**
Convert to Taiwanese equivalents with same register and impact.
- Maintain comedic/dramatic effect
- Match formality level

**Condensation:**
Balance readability and fidelity:
- Remove non-essential fillers
- Preserve core meaning
- Prioritize natural flow

{taiwanese_colloquial}
{netflix_rules}
{translation_enhancement_rules}

Output the translated text directly. No preamble, no explanations.
""",
            },
        }

    def _load_config(self) -> None:
        """讀取配置並確保必要的設定存在"""
        # 如果配置檔案不存在，將使用配置管理器中的預設值
        default_values = {
            "current_content_type": "general",
            "current_style": "standard",
            "current_language_pair": "日文→繁體中文",
            "custom_prompts": {},
            "version_history": {},
            "last_updated": datetime.now().isoformat(),
        }

        # 確保所有預設值都存在於配置中
        for key, value in default_values.items():
            if not self.config_manager.get_value(key, None):
                self.config_manager.set_value(key, value, auto_save=False)

        # 儲存配置
        self.config_manager.save_config()

    def _config_changed(self, config_type: str, config: dict[str, Any]) -> None:
        """配置變更時的回調函數

        參數:
            config_type: 配置類型
            config: 配置內容
        """
        if config_type != "prompt":
            return

        # 更新當前設定
        self.current_content_type = config.get("current_content_type", self.current_content_type)
        self.current_style = config.get("current_style", self.current_style)
        self.current_language_pair = config.get("current_language_pair", self.current_language_pair)

        # 更新自訂提示詞和版本歷史
        self.custom_prompts = config.get("custom_prompts", self.custom_prompts)
        self.version_history = config.get("version_history", self.version_history)

        logger.debug("提示詞配置已更新")

    def _load_custom_prompts(self) -> None:
        """載入所有自訂提示詞"""
        # 首先從配置中載入已儲存的自訂提示詞
        self.custom_prompts = self.config_manager.get_value("custom_prompts", default={}) or {}

        # 確保所有內容類型都存在
        for content_type in ["general", "adult", "anime", "movie", "english_drama"]:
            if content_type not in self.custom_prompts:
                self.custom_prompts[content_type] = {}

            # 檢查是否有對應的模板檔案
            template_file = os.path.join(self.templates_dir, f"{content_type}_template.json")
            if os.path.exists(template_file):
                try:
                    with open(template_file, encoding="utf-8") as f:
                        templates = json.load(f)

                    # 合併模板內容
                    for llm_type, prompt in templates.items():
                        if llm_type not in self.custom_prompts[content_type]:
                            self.custom_prompts[content_type][llm_type] = prompt

                    logger.debug(f"已載入模板: {template_file}")
                except Exception as e:
                    logger.error(f"載入模板檔案時發生錯誤: {format_exception(e)}")

        # 更新配置
        self.config_manager.set_value("custom_prompts", self.custom_prompts)

    def get_batch_line_mapping_instruction(self) -> str:
        """取得批次翻譯的嚴格行對行映射指令

        用於結構-文本分離工作流中，確保 LLM 輸出行數與輸入完全一致。
        此指令不會加入預設 prompt，僅供批次翻譯模式調用。

        回傳:
            嚴格行對行映射指令文本
        """
        return """
## Strict Line Mapping (CRITICAL):
Your output MUST have EXACTLY the same number of lines as the input.
Each input line maps to exactly one output line — no exceptions.
- If input has N lines, output MUST have exactly N lines
- Do NOT merge lines, skip lines, or add extra lines
- Do NOT add blank lines or explanatory text between translations
- Preserve literal \\n (two characters: backslash + n) when present in a line
- Count your output lines carefully before submitting
"""

    def _normalize_model_name(self, model_name: str | None) -> str:
        """標準化模型名稱，便於做模型特化判斷"""
        if not model_name:
            return ""
        return model_name.strip().lower().split("@", maxsplit=1)[0]

    def _is_qwen35_family_model(self, model_name: str | None) -> bool:
        """判斷是否為 Qwen3.5 家族模型"""
        normalized = self._normalize_model_name(model_name)
        return bool(re.search(r"qwen(?:[-_/\s]?3\.5|35)", normalized))

    def _is_qwen35_ud_model(self, model_name: str | None) -> bool:
        """判斷是否為 qwen3.5-ud 類型模型"""
        normalized = self._normalize_model_name(model_name)
        if not normalized or not self._is_qwen35_family_model(normalized):
            return False

        tokens = [token for token in re.split(r"[^a-z0-9]+", normalized) if token]
        return "ud" in tokens

    def _should_use_qwen35_ud_adult_prompt(self, llm_type: str, content_type: str, model_name: str | None) -> bool:
        """判斷是否應使用 qwen3.5-ud 的成人字幕特化 prompt"""
        return llm_type in {"ollama", "llamacpp"} and content_type == "adult" and self._is_qwen35_ud_model(model_name)

    def _get_qwen35_ud_adult_prompt(self) -> str:
        """取得 qwen3.5-ud 專用的成人字幕短 prompt"""
        return """
You translate Japanese adult subtitles into natural Taiwan Traditional Chinese.
Rules:
1. Translate ONLY the CURRENT line. Never translate or copy context.
2. Keep the exact same number of lines and line breaks. If the source is single-line, output a single line only.
3. Output ONLY the translated subtitle text. No labels, quotes, explanations, or extra notes.
4. Do not end the output with 。 or ，.
5. Do not censor, soften, or moralize sexual wording.
6. Preserve who does the action to whom.
7. Preserve imperative tone, body-part target, penetration direction, and ejaculation intent accurately.
8. When the source is short or ambiguous, stay literal to the action instead of inventing softer wording.
9. Keep Japanese personal names and nicknames in their original Japanese form. Do not translate or romanize names into Chinese characters.
10. Use concise Taiwan Traditional Chinese suitable for spoken subtitles.
""".strip()

    def _resolve_default_prompt_llm_type(self, llm_type: str) -> str:
        """將 runtime/provider 名稱對齊到 prompt 模板實際維護的 key。"""
        return PROMPT_PROVIDER_FALLBACKS.get(llm_type, llm_type)

    def _get_default_prompt_text(self, content_type: str, llm_type: str) -> str:
        """取得 provider 對應的預設 prompt，必要時回退到相近家族。"""
        resolved_content_type = content_type if content_type in self.default_prompts else "general"
        prompt_group = self.default_prompts.get(resolved_content_type, self.default_prompts["general"])
        resolved_llm_type = self._resolve_default_prompt_llm_type(llm_type)

        return prompt_group.get(resolved_llm_type) or self.default_prompts["general"].get(
            resolved_llm_type, self.default_prompts["general"]["ollama"]
        )

    def _get_message_strategy_signature(
        self,
        llm_type: str,
        content_type: str | None = None,
        model_name: str | None = None,
    ) -> str:
        """取得訊息結構策略版本，用於快取區分"""
        resolved_content_type = content_type or self.current_content_type
        if self._should_use_qwen35_ud_adult_prompt(llm_type, resolved_content_type, model_name):
            return "qwen35_ud_adult_compact_context_v3"
        return "default_structured_context_v1"

    def _resolve_context_index(
        self, text: str, context_texts: list[str], current_index: int | None = None
    ) -> int | None:
        """解析目前字幕在 context_texts 中的索引。

        優先使用呼叫端傳入的 current_index，避免重複句被 list.index()
        指到錯誤位置。若未提供，則回退到最接近上下文中心的匹配項。
        """
        if current_index is not None:
            if 0 <= current_index < len(context_texts):
                if context_texts[current_index] == text:
                    return current_index
                logger.warning("提供的 current_index 與當前文字不符，退回自動解析")
            else:
                logger.warning("提供的 current_index 超出 context_texts 範圍，退回自動解析")

        match_indices = [idx for idx, candidate in enumerate(context_texts) if candidate == text]
        if not match_indices:
            return None

        if len(match_indices) == 1:
            return match_indices[0]

        center = (len(context_texts) - 1) / 2
        return min(match_indices, key=lambda idx: (abs(idx - center), idx))

    def _split_context_texts(
        self, text: str, context_texts: list[str], current_index: int | None = None
    ) -> tuple[list[str], list[str], int | None]:
        """拆分前後文並回傳解析出的目前索引。"""
        resolved_index = self._resolve_context_index(text, context_texts, current_index)
        if resolved_index is None:
            return context_texts, [], None

        context_before = context_texts[:resolved_index]
        context_after = context_texts[resolved_index + 1 :]
        return context_before, context_after, resolved_index

    def get_effective_context_texts(
        self, text: str, context_texts: list[str], llm_type: str, model_name: str, current_index: int | None = None
    ) -> list[str]:
        """回傳實際用於 prompt 的壓縮後上下文列表。"""
        content_type = self.current_content_type
        if not self._should_use_qwen35_ud_adult_prompt(llm_type, content_type, model_name):
            return context_texts

        context_before, context_after, resolved_index = self._split_context_texts(text, context_texts, current_index)
        if resolved_index is None:
            return context_texts

        compacted_before, compacted_after = self._compact_qwen35_ud_context(text, context_before, context_after)
        return [*compacted_before, text, *compacted_after]

    def get_effective_cache_context_texts(
        self, text: str, context_texts: list[str], llm_type: str, model_name: str, current_index: int | None = None
    ) -> list[str]:
        """回傳供快取鍵使用的上下文列表。

        額外加入 current_index 標記，避免重複句在相同上下文中產生快取鍵碰撞。
        """
        relaxed_context = self._get_qwen35_ud_short_line_cache_context(
            text,
            context_texts,
            llm_type,
            model_name,
            current_index=current_index,
        )
        if relaxed_context is not None:
            return relaxed_context

        effective_context = self.get_effective_context_texts(
            text, context_texts, llm_type, model_name, current_index=current_index
        )
        resolved_index = self._resolve_context_index(text, context_texts, current_index)
        if resolved_index is None:
            return effective_context
        return [f"[CURRENT_INDEX]{resolved_index}", *effective_context]

    def _get_qwen35_ud_short_line_cache_context(
        self,
        text: str,
        context_texts: list[str],
        llm_type: str,
        model_name: str,
        current_index: int | None = None,
    ) -> list[str] | None:
        """為 qwen3.5-ud 的短句建立較寬鬆的快取鍵上下文。"""
        if not self._should_use_qwen35_ud_adult_prompt(llm_type, self.current_content_type, model_name):
            return None
        if not self._is_qwen35_ud_short_cache_candidate(text):
            return None

        context_before, context_after, _ = self._split_context_texts(text, context_texts, current_index)
        nearby_context = [*context_before[-1:], *context_after[:1]]

        context_class_tokens = []
        if any(self._contains_qwen35_ud_adult_action_markers(candidate) for candidate in nearby_context):
            context_class_tokens.append("adult_action_nearby")
        if any("?" in candidate or "？" in candidate for candidate in nearby_context):
            context_class_tokens.append("question_nearby")
        if not context_class_tokens:
            context_class_tokens.append("plain")

        context_class = "+".join(context_class_tokens)
        return [
            "[CACHE_MODE]qwen35_ud_short_utterance_v1",
            f"[CONTEXT_CLASS]{context_class}",
        ]

    def _is_qwen35_ud_short_cache_candidate(self, text: str) -> bool:
        """判斷是否適合使用較寬鬆的短句快取鍵。"""
        if "\n" in text:
            return False

        normalized = re.sub(r"[、，。．！？!?…・「」『』（）()【】\s]", "", text)
        if not normalized or len(normalized) > 8:
            return False

        return bool(re.fullmatch(r"[ぁ-ゖゝゞァ-ヶー]+", normalized))

    def _contains_qwen35_ud_adult_action_markers(self, text: str) -> bool:
        """判斷文字是否包含 qwen3.5-ud 容易被上下文帶偏的成人動作標記"""
        markers = (
            "舐め",
            "なめ",
            "しゃぶ",
            "フェラ",
            "咥",
            "乳首",
            "まんこ",
            "おまんこ",
            "ちんこ",
            "ちんぽ",
            "ペニス",
            "根元",
            "奥",
            "ビンビン",
            "硬",
            "挿",
            "入れ",
            "出して",
            "出ちゃ",
            "イク",
            "イっ",
            "中出し",
        )
        compact_text = re.sub(r"\s+", "", text)
        return any(marker in compact_text for marker in markers)

    def _compact_qwen35_ud_context(
        self, text: str, context_before: list[str], context_after: list[str]
    ) -> tuple[list[str], list[str]]:
        """為 qwen3.5-ud 壓縮成人字幕上下文，降低短句漂移與卡住風險"""
        trimmed_before = context_before[-1:]
        trimmed_after = context_after[:1]

        compact_text = re.sub(r"\s+", "", text)
        should_drop_context = (
            "\n" not in text and len(compact_text) <= 24 and self._contains_qwen35_ud_adult_action_markers(compact_text)
        )

        if should_drop_context:
            return [], []

        return trimmed_before, trimmed_after

    def _build_qwen35_ud_user_message(self, text: str, context_before: list[str], context_after: list[str]) -> str:
        """建立 qwen3.5-ud 專用的精簡 user message"""
        parts = ["CURRENT:", text]

        if context_before or context_after:
            parts.extend(["", "REFERENCE ONLY. DO NOT TRANSLATE OR COPY."])

            if context_before:
                parts.append(f"Before: {context_before[-1]}")
            if context_after:
                parts.append(f"After: {context_after[0]}")

        return "\n".join(parts)

    def get_prompt(
        self,
        llm_type: str = "ollama",
        content_type: str | None = None,
        style: str | None = None,
        model_name: str | None = None,
    ) -> str:
        """根據 LLM 類型、內容類型和風格取得適合的 Prompt

        參數:
            llm_type: LLM類型 (如 "ollama" 或 "openai")
            content_type: 內容類型，若為None則使用當前設定
            style: 翻譯風格，若為None則使用當前設定
            model_name: 模型名稱，用於套用模型特化 prompt

        回傳:
            提示詞文本
        """
        # 使用指定的內容類型和風格，或使用當前設定
        content_type = content_type or self.current_content_type
        style = style or self.current_style

        # 檢查是否有自訂提示詞
        if content_type in self.custom_prompts and llm_type in self.custom_prompts[content_type]:
            prompt = self.custom_prompts[content_type][llm_type]
        elif self._should_use_qwen35_ud_adult_prompt(llm_type, content_type, model_name):
            prompt = self._get_qwen35_ud_adult_prompt()
        else:
            prompt = self._get_default_prompt_text(content_type, llm_type)

        # 套用風格修飾符（如果不是標準風格）
        if style != "standard":
            prompt = self._apply_style_modifier(prompt, style, llm_type)

        # 套用語言對修飾符
        prompt = self._apply_language_pair_modifier(prompt, self.current_language_pair)

        return prompt.strip()

    def get_prompt_version(
        self,
        llm_type: str = "ollama",
        content_type: str | None = None,
        style: str | None = None,
        model_name: str | None = None,
    ) -> str:
        """取得提示詞版本雜湊（用於快取 key）

        參數:
            llm_type: LLM類型
            content_type: 內容類型
            style: 翻譯風格
            model_name: 模型名稱

        回傳:
            提示詞內容的 MD5 雜湊前 8 位
        """
        import hashlib

        resolved_content_type = content_type or self.current_content_type
        prompt = self.get_prompt(llm_type, resolved_content_type, style, model_name=model_name)
        strategy = self._get_message_strategy_signature(llm_type, resolved_content_type, model_name)
        fingerprint = f"{prompt}\n\n[MESSAGE_STRATEGY]{strategy}"
        return hashlib.md5(fingerprint.encode()).hexdigest()[:8]

    def get_optimized_message(
        self,
        text: str,
        context_texts: list[str],
        llm_type: str,
        model_name: str,
        current_index: int | None = None,
    ) -> list[dict[str, str]]:
        """根據不同LLM和模型生成優化的提示訊息格式

        參數:
            text: 要翻譯的文字
            context_texts: 上下文文本列表（包含前文、當前文本、後文）
            llm_type: LLM類型 (如 "ollama" 或 "openai")
            model_name: 模型名稱

        回傳:
            適合API請求的訊息列表
        """
        # 獲取基本提示詞
        content_type = self.current_content_type
        prompt = self.get_prompt(llm_type, model_name=model_name)

        # 構建結構化的上下文訊息
        # context_texts 包含當前字幕及其前後文，需要分離出來
        context_before = []
        context_after = []

        context_before, context_after, resolved_index = self._split_context_texts(text, context_texts, current_index)
        if resolved_index is None:
            # 如果找不到當前文本（極少數情況），使用原有方式
            logger.warning("無法在上下文中找到當前文本，使用舊格式")
            context_before = context_texts
            context_after = []

        use_qwen35_ud_strategy = self._should_use_qwen35_ud_adult_prompt(llm_type, content_type, model_name)
        if use_qwen35_ud_strategy:
            context_before, context_after = self._compact_qwen35_ud_context(text, context_before, context_after)

        # 檢測句子是否以連接詞結尾
        conjunctions = [
            "when",
            "if",
            "because",
            "although",
            "while",
            "before",
            "after",
            "unless",
            "though",
            "since",
            "until",
            "as",
            "where",
            "whereas",
        ]
        text_lower = text.strip().lower()
        ends_with_conjunction = any(text_lower.endswith(f" {conj}") for conj in conjunctions)

        # 構建新格式的 user message
        if use_qwen35_ud_strategy:
            user_message = self._build_qwen35_ud_user_message(text, context_before, context_after)
        else:
            user_content_parts = []

            # 如果以連接詞結尾，添加超強警告
            if ends_with_conjunction:
                detected_conj = next(conj for conj in conjunctions if text_lower.endswith(f" {conj}"))
                user_content_parts.extend(
                    [
                        "🚨 **MANDATORY WARNING** 🚨",
                        f"The [CURRENT] sentence ends with the conjunction '{detected_conj.upper()}'.",
                        f"YOU **MUST** PRESERVE '{detected_conj.upper()}' in your translation.",
                        'DO NOT remove it. DO NOT omit it. DO NOT "complete" the sentence.',
                        "Keep the translation incomplete, matching the original structure.",
                        "",
                        "---",
                        "",
                    ]
                )

            user_content_parts.extend(["[CURRENT] (請只翻譯這一句):", text, ""])

            if context_before:
                user_content_parts.append("[CONTEXT_BEFORE] (前文參考，不要翻譯):")
                for ctx in context_before:
                    user_content_parts.append(f"- {ctx}")
                user_content_parts.append("")

            if context_after:
                user_content_parts.append("[CONTEXT_AFTER] (後文參考，不要翻譯):")
                for ctx in context_after:
                    user_content_parts.append(f"- {ctx}")

            user_message = "\n".join(user_content_parts)

        # 為不同的LLM類型創建不同格式的訊息
        if llm_type == "openai" or llm_type == "anthropic":
            # OpenAI/Anthropic的訊息格式
            messages = [{"role": "system", "content": prompt}, {"role": "user", "content": user_message}]
        else:
            # Ollama等其他LLM的訊息格式
            messages = [{"role": "system", "content": prompt}, {"role": "user", "content": user_message}]

        return messages

    def _apply_style_modifier(self, prompt: str, style: str, llm_type: str) -> str:
        """根據翻譯風格修改提示詞

        參數:
            prompt: 原始提示詞
            style: 翻譯風格
            llm_type: LLM類型

        回傳:
            修改後的提示詞
        """
        style_modifiers = {
            "literal": {
                "ollama": "Focus on providing a more literal translation that is closer to the original text meaning. Prioritize accuracy to source text over natural flow in the target language. Remember to ONLY translate the CURRENT text, not context.",
                "openai": "Translate literally. Prioritize source accuracy over target fluency. Only translate the current text, never context.",
            },
            "localized": {
                "ollama": "Focus on adapting the content to the target culture. Use Taiwan-specific expressions, cultural references, and idioms where appropriate to make the translation feel natural to local readers. Remember to ONLY translate the CURRENT text, not context.",
                "openai": "Translate with cultural adaptation. Use Taiwan expressions and references. Only translate the current text, never context.",
            },
            "specialized": {
                "ollama": "Focus on accurate translation of terminology relevant to the content domain. Prioritize precision in specialized terms and concepts. Remember to ONLY translate the CURRENT text, not context.",
                "openai": "Translate with domain precision. Prioritize accurate terminology. Only translate the current text, never context.",
            },
        }

        resolved_llm_type = self._resolve_default_prompt_llm_type(llm_type)

        if style in style_modifiers and resolved_llm_type in style_modifiers[style]:
            modifier = style_modifiers[style][resolved_llm_type]
            # 在提示詞結尾添加風格修飾符
            return f"{prompt}\n\nAdditional instruction: {modifier}"

        return prompt

    def _apply_language_pair_modifier(self, prompt: str, language_pair: str) -> str:
        """根據語言對修改提示詞

        參數:
            prompt: 原始提示詞
            language_pair: 語言對 (如 "日文→繁體中文")

        回傳:
            修改後的提示詞
        """
        # 如果是預設的日文→繁體中文，不需要修改
        if language_pair == "日文→繁體中文":
            return prompt

        # 取得來源語言和目標語言
        if language_pair in self.language_pairs:
            source = self.language_pairs[language_pair]["source"]
            target = self.language_pairs[language_pair]["target"]

            # 基於正則表達式更新提示詞中的語言引用
            # 尋找並替換繁體中文/Taiwan Mandarin 等相關提示
            prompt = re.sub(r"(Taiwan Mandarin|繁體中文|Traditional Chinese)", target, prompt)

            # 添加明確的語言對說明
            language_instruction = (
                f"\nTranslate from {source} to {target}. Remember to ONLY translate the CURRENT text, not context."
            )
            return f"{prompt}{language_instruction}"

        return prompt

    def set_prompt(self, new_prompt: str, llm_type: str = "ollama", content_type: str | None = None) -> bool:
        """設置特定 LLM 和內容類型的提示詞

        參數:
            new_prompt: 新的提示詞
            llm_type: LLM類型 (如 "ollama" 或 "openai")
            content_type: 內容類型，若為None則使用當前設定

        回傳:
            是否設置成功
        """
        content_type = content_type or self.current_content_type

        # 確保自訂提示詞字典中有對應的內容類型
        if content_type not in self.custom_prompts:
            self.custom_prompts[content_type] = {}

        # 儲存舊的提示詞版本
        old_prompt = self.custom_prompts.get(content_type, {}).get(llm_type)
        if old_prompt:
            self._add_to_version_history(content_type, llm_type, old_prompt)

        # 更新提示詞
        self.custom_prompts[content_type][llm_type] = new_prompt.strip()

        # 更新配置
        self.config_manager.set_value("custom_prompts", self.custom_prompts)

        # 儲存至模板檔案
        self._save_prompt_template(content_type)

        logger.info(f"已設置 '{content_type}' 類型的 '{llm_type}' 提示詞")
        return True

    def _add_to_version_history(self, content_type: str, llm_type: str, prompt: str) -> None:
        """將提示詞添加到版本歷史

        參數:
            content_type: 內容類型
            llm_type: LLM類型
            prompt: 提示詞
        """
        if content_type not in self.version_history:
            self.version_history[content_type] = {}

        if llm_type not in self.version_history[content_type]:
            self.version_history[content_type][llm_type] = []

        # 添加版本記錄
        version_entry = {
            "prompt": prompt,
            "timestamp": datetime.now().isoformat(),
            "version": len(self.version_history[content_type][llm_type]) + 1,
        }

        # 維護最多 10 個版本
        history = self.version_history[content_type][llm_type]
        history.append(version_entry)
        if len(history) > 10:
            history = history[-10:]  # 只保留最新的 10 個版本
            self.version_history[content_type][llm_type] = history

        # 更新配置
        self.config_manager.set_value("version_history", self.version_history)

    def _save_prompt_template(self, content_type: str) -> bool:
        """儲存提示詞模板至檔案

        參數:
            content_type: 內容類型

        回傳:
            是否儲存成功
        """
        template_file = os.path.join(self.templates_dir, f"{content_type}_template.json")
        try:
            # 確保目錄存在
            os.makedirs(self.templates_dir, exist_ok=True)

            with open(template_file, "w", encoding="utf-8") as f:
                json.dump(self.custom_prompts[content_type], f, ensure_ascii=False, indent=4)
            logger.debug(f"已儲存模板至: {template_file}")
            return True
        except Exception as e:
            logger.error(f"儲存模板檔案時發生錯誤: {format_exception(e)}")
            return False

    def get_version_history(self, content_type: str | None = None, llm_type: str | None = None) -> list[dict[str, Any]]:
        """取得提示詞的版本歷史

        參數:
            content_type: 內容類型，若為None則使用當前設定
            llm_type: LLM類型，若為None則返回所有LLM類型的歷史

        回傳:
            版本歷史列表
        """
        content_type = content_type or self.current_content_type

        if content_type not in self.version_history:
            return []

        if llm_type:
            return list(self.version_history[content_type].get(llm_type, []))

        # 合併所有 LLM 類型的歷史記錄
        all_history = []
        for llm, history in self.version_history[content_type].items():
            for entry in history:
                entry_with_llm = entry.copy()
                entry_with_llm["llm_type"] = llm
                all_history.append(entry_with_llm)

        # 按時間排序
        all_history.sort(key=lambda x: x["timestamp"], reverse=True)
        return all_history

    def restore_version(self, content_type: str, llm_type: str, version_index: int) -> bool:
        """恢復到特定版本的提示詞

        參數:
            content_type: 內容類型
            llm_type: LLM類型
            version_index: 版本索引

        回傳:
            是否恢復成功
        """
        if (
            content_type in self.version_history
            and llm_type in self.version_history[content_type]
            and 0 <= version_index < len(self.version_history[content_type][llm_type])
        ):
            # 取得要恢復的版本
            version = self.version_history[content_type][llm_type][version_index]

            # 設置提示詞
            self.set_prompt(version["prompt"], llm_type, content_type)

            logger.info(f"已恢復 '{content_type}' 類型的 '{llm_type}' 提示詞到版本 {version['version']}")
            return True

        logger.warning("無法恢復版本，找不到對應的版本記錄")
        return False

    def reset_to_default(self, llm_type: str | None = None, content_type: str | None = None) -> bool:
        """重置為預設提示詞

        參數:
            llm_type: LLM類型，若為None則重置所有LLM類型
            content_type: 內容類型，若為None則使用當前設定

        回傳:
            是否重置成功
        """
        content_type = content_type or self.current_content_type
        if content_type not in self.default_prompts:
            return False

        if llm_type:
            default_prompt = self._get_default_prompt_text(content_type, llm_type)
            self.set_prompt(default_prompt, llm_type, content_type)
            logger.info(f"已重置 '{content_type}' 類型的 '{llm_type}' 提示詞為預設值")
            return True
        else:
            # 重置所有 LLM 類型的提示詞
            success = True
            for llm in SUPPORTED_PROMPT_LLM_TYPES:
                result = self.set_prompt(self._get_default_prompt_text(content_type, llm), llm, content_type)
                success = success and result
            logger.info(f"已重置 '{content_type}' 類型的所有提示詞為預設值")
            return success

        return False

    def set_content_type(self, content_type: str) -> bool:
        """設置當前使用的內容類型

        參數:
            content_type: 內容類型

        回傳:
            是否設置成功
        """
        if content_type in ["general", "adult", "anime", "movie", "english_drama"]:
            self.current_content_type = content_type
            self.config_manager.set_value("current_content_type", content_type)
            logger.info(f"已設置當前內容類型為: {content_type}")
            return True
        return False

    def set_translation_style(self, style: str) -> bool:
        """設置當前使用的翻譯風格

        參數:
            style: 翻譯風格

        回傳:
            是否設置成功
        """
        if style in self.translation_styles:
            self.current_style = style
            self.config_manager.set_value("current_style", style)
            logger.info(f"已設置當前翻譯風格為: {style}")
            return True
        return False

    def set_language_pair(self, language_pair: str) -> bool:
        """設置當前使用的語言對

        參數:
            language_pair: 語言對

        回傳:
            是否設置成功
        """
        if language_pair in self.language_pairs:
            self.current_language_pair = language_pair
            self.config_manager.set_value("current_language_pair", language_pair)
            logger.info(f"已設置當前語言對為: {language_pair}")
            return True
        return False

    def get_available_content_types(self) -> list[str]:
        """取得可用的內容類型

        回傳:
            內容類型列表
        """
        return ["general", "adult", "anime", "movie", "english_drama"]

    def get_available_styles(self) -> dict[str, str]:
        """取得可用的翻譯風格

        回傳:
            翻譯風格字典 {風格代碼: 風格描述}
        """
        return self.translation_styles

    def get_available_language_pairs(self) -> list[str]:
        """取得可用的語言對

        回傳:
            語言對列表
        """
        return list(self.language_pairs.keys())

    def export_prompt(
        self, content_type: str | None = None, llm_type: str | None = None, file_path: str | None = None
    ) -> str | None:
        """匯出提示詞至檔案

                參數:
                    content_type: 內容類型，若為None則使用當前設定
                    llm_type: LLM類型，若為None則匯出所有LLM類型的提示詞
                    file_path: 輸出檔案路徑，若為None則自動生成

                回傳:
        匯出檔案路徑，若失敗則回傳None
        """
        content_type = content_type or self.current_content_type

        # 要匯出的資料
        export_data = {
            "metadata": {"exported_at": datetime.now().isoformat(), "content_type": content_type, "version": "1.0"},
            "prompts": {},
        }

        if llm_type:
            # 匯出特定 LLM 的提示詞
            if content_type in self.custom_prompts and llm_type in self.custom_prompts[content_type]:
                export_data["prompts"][llm_type] = self.custom_prompts[content_type][llm_type]
            else:
                export_data["prompts"][llm_type] = self._get_default_prompt_text(content_type, llm_type)
        else:
            # 匯出所有 LLM 的提示詞
            for llm in SUPPORTED_PROMPT_LLM_TYPES:
                if content_type in self.custom_prompts and llm in self.custom_prompts[content_type]:
                    export_data["prompts"][llm] = self.custom_prompts[content_type][llm]
                else:
                    export_data["prompts"][llm] = self._get_default_prompt_text(content_type, llm)

        # 生成輸出檔案路徑
        if not file_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name = f"prompt_export_{content_type}_{timestamp}.json"
            file_path = os.path.join(self.templates_dir, file_name)

        try:
            # 確保目錄存在
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=4)
            logger.info(f"已匯出提示詞至: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"匯出提示詞時發生錯誤: {format_exception(e)}")
            return None

    def import_prompt(self, input_path: str) -> bool:
        """從檔案匯入提示詞

        參數:
            input_path: 輸入檔案路徑

        回傳:
            是否匯入成功
        """
        try:
            if not os.path.exists(input_path):
                logger.error(f"匯入檔案不存在: {input_path}")
                return False

            with open(input_path, encoding="utf-8") as f:
                import_data = json.load(f)

            # 驗證匯入資料格式
            if not all(k in import_data for k in ["metadata", "prompts"]):
                logger.warning(f"無效的提示詞匯入格式: {input_path}")
                return False

            content_type = import_data["metadata"].get("content_type", "general")

            # 匯入提示詞
            for llm_type, prompt in import_data["prompts"].items():
                if llm_type not in SUPPORTED_PROMPT_LLM_TYPES:
                    logger.warning(f"跳過不支援的LLM類型: {llm_type}")
                    continue
                self.set_prompt(prompt, llm_type, content_type)

            logger.info(f"已從 {input_path} 匯入 '{content_type}' 類型的提示詞")
            return True
        except Exception as e:
            logger.error(f"匯入提示詞時發生錯誤: {format_exception(e)}")
            return False

    def analyze_prompt(self, prompt: str) -> dict[str, Any]:
        """分析提示詞文本的品質得分

        參數:
            prompt: 要分析的提示詞文本

        回傳:
            分析結果字典
        """
        analysis = {
            "length": len(prompt),
            "word_count": len(prompt.split()),
            "contains_rules": False,
            "contains_examples": False,
            "contains_constraints": False,
            "clarity": 0,
            "specificity": 0,
            "completeness": 0,
            "formatting_score": 0,
            "quality_score": 0,
        }
        # 檢測是否包含規則
        if re.search(r"(rule|guidelines|follow these|instructions|請遵守)", prompt, re.IGNORECASE):
            analysis["contains_rules"] = True
            analysis["clarity"] += 1

        # 檢測是否包含例子
        if re.search(r"(example|for instance|such as|舉例|例如)", prompt, re.IGNORECASE):
            analysis["contains_examples"] = True
            analysis["specificity"] += 1

        # 檢測是否包含約束條件
        if re.search(r"(only|must|should|do not|avoid|禁止|不要|必須)", prompt, re.IGNORECASE):
            analysis["contains_constraints"] = True
            analysis["completeness"] += 1

        # 檢測格式化程度
        if prompt.count("\n") > 3:
            analysis["formatting_score"] += 1

        if re.search(r"(\d+\.|\*|-|\d+\))", prompt):
            analysis["formatting_score"] += 1

        # 計算總體得分
        analysis["clarity"] += min(3, prompt.count(".") // 3)
        analysis["specificity"] += min(
            3, len(re.findall(r"\b(translate|翻譯|maintain|保持|preserve|keep|確保)\b", prompt, re.IGNORECASE))
        )
        analysis["completeness"] += min(
            3, len(re.findall(r"\b(tone|style|context|語氣|風格|上下文)\b", prompt, re.IGNORECASE))
        )

        # 調整分數範圍 (0-5)
        for key in ["clarity", "specificity", "completeness", "formatting_score"]:
            analysis[key] = min(5, analysis[key])

        # 計算總體品質得分 (0-100)
        analysis["quality_score"] = (
            (analysis["clarity"] * 20)
            + (analysis["specificity"] * 20)
            + (analysis["completeness"] * 20)
            + (analysis["formatting_score"] * 10)
            + (30 if analysis["contains_rules"] and analysis["contains_constraints"] else 0)
        ) // 5

        return analysis
