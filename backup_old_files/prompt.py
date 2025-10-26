import os
import re
import json
import logging
import time
from typing import List, Dict, Any, Optional, Tuple, Union, Set
from datetime import datetime
from pathlib import Path
import logging.handlers
import threading

# 從配置管理器導入
from config_manager import ConfigManager, get_config, set_config
from utils import safe_execute, format_exception, AppError

# 設定日誌記錄
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# 確保日誌目錄存在
os.makedirs('logs', exist_ok=True)

# 避免重複添加處理程序
if not logger.handlers:
    handler = logging.handlers.TimedRotatingFileHandler(
        filename='logs/prompt_manager.log',
        when='midnight',
        interval=1,
        backupCount=7,
        encoding='utf-8'
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
    def get_instance(cls, config_file: str = None) -> 'PromptManager':
        """獲取提示詞管理器的單例實例
        
        參數:
            config_file: 配置檔案路徑，若為None則使用預設路徑
            
        回傳:
            提示詞管理器實例
        """
        with cls._lock:
            if cls._instance is None:
                # 如果沒有指定config_file，從配置獲取
                if config_file is None:
                    config_file = get_config("prompt", "config_file", "config/prompt_config.json")
                
                cls._instance = PromptManager(config_file)
            return cls._instance
    
    def __init__(self, config_file: str = "config/prompt_config.json"):
        """初始化提示詞管理器
        
        參數:
            config_file: 配置檔案路徑
        """
        self.config_file = config_file
        self.config_dir = os.path.dirname(config_file) or "."
        self.templates_dir = os.path.join(self.config_dir, "prompt_templates")
        
        # 確保模板目錄存在
        os.makedirs(self.templates_dir, exist_ok=True)
        
        # 獲取配置管理器實例
        self.config_manager = ConfigManager.get_instance("prompt")
        
        # 翻譯風格定義
        self.translation_styles = {
            "standard": "標準翻譯 - 平衡準確性和自然度",
            "literal": "直譯 - 更忠於原文的字面意思",
            "localized": "本地化翻譯 - 更適合台灣繁體中文文化",
            "specialized": "專業翻譯 - 保留專業術語"
        }
        
        # 語言組合映射
        self.language_pairs = {
            "日文→繁體中文": {"source": "日文", "target": "繁體中文"},
            "英文→繁體中文": {"source": "英文", "target": "繁體中文"},
            "繁體中文→英文": {"source": "繁體中文", "target": "英文"},
            "簡體中文→繁體中文": {"source": "簡體中文", "target": "繁體中文"},
            "韓文→繁體中文": {"source": "韓文", "target": "繁體中文"},
            "法文→繁體中文": {"source": "法文", "target": "繁體中文"},
            "德文→繁體中文": {"source": "德文", "target": "繁體中文"},
            "西班牙文→繁體中文": {"source": "西班牙文", "target": "繁體中文"},
            "俄文→繁體中文": {"source": "俄文", "target": "繁體中文"}
        }
        
        # 預設提示詞
        self.default_prompts = self._get_default_prompts()
        
        # 載入設定
        self._load_config()
        
        # 設定當前使用的內容類型和風格
        self.current_content_type = self.config_manager.get_value("current_content_type", "general")
        self.current_style = self.config_manager.get_value("current_style", "standard")
        self.current_language_pair = self.config_manager.get_value("current_language_pair", "日文→繁體中文")
        
        # 載入版本歷史
        self.version_history = self.config_manager.get_value("version_history", {})
        
        # 載入自訂提示詞
        self.custom_prompts = self.config_manager.get_value("custom_prompts", {})
        self._load_custom_prompts()
        
        # 設置配置變更監聽器
        self.config_manager.add_listener(self._config_changed)
        
        logger.info("PromptManager 初始化完成")
    
    def _get_default_prompts(self) -> Dict[str, Dict[str, str]]:
        """獲取預設提示詞，從配置檔案或內置預設值"""
        # 嘗試從配置獲取預設提示詞
        default_config = ConfigManager.get_instance("default_prompt")
        default_prompts = default_config.get_value("default_prompts", None)
        
        if default_prompts:
            return default_prompts
        
        # 如果配置中沒有，使用內置預設值
        return {
            "general": {
                "ollama": """
You are a professional subtitle translator. Your task is to translate subtitles accurately.
Please strictly follow these rules:
1. Only translate the CURRENT text sent to you, NOT any context text.
2. Preserve the exact number of lines in the original text.
3. Keep all formatting, including newlines, in the exact same positions.
4. Maintain the original tone and expression style.
5. Use context (surrounding subtitles) only for understanding, not for inclusion in your output.
6. Translate into natural Taiwan Mandarin Chinese expressions.
7. Your response must contain ONLY the translated text, nothing else.
""",
                "openai": """
You are a high-efficiency subtitle translator. Your task:
1. ONLY translate the CURRENT text, nothing else. No warnings, explanations, or quotes.
2. Preserve the exact number of lines and formatting of the original.
3. Maintain original tone and style. Translate to Taiwan Mandarin.
4. Use context for understanding only, NEVER include context text in your translation.
5. Be concise and direct - output ONLY the translated text.
"""
            },
            "adult": {
                "ollama": """
You are a professional translator for adult video subtitles. 
Please strictly follow these rules:
1. Only translate the CURRENT text sent to you, NOT any context text.
2. Preserve the exact number of lines in the original text.
3. Keep all formatting, including newlines, in the exact same positions.
4. Maintain the original tone and expression style.
5. Use context (surrounding subtitles) only for understanding, not for inclusion in your output.
6. Translate into natural Taiwan Mandarin Chinese expressions with appropriate adult terminology.
7. Your response must contain ONLY the translated text, nothing else.
""",
                "openai": """
You are a high-efficiency adult content subtitle translator. Your task:
1. ONLY translate the CURRENT text, nothing else. No warnings, explanations, or quotes.
2. Preserve the exact number of lines and formatting of the original.
3. Maintain original tone and style. Translate to Taiwan Mandarin.
4. Use appropriate adult terminology in the target language.
5. Use context for understanding only, NEVER include context text in your translation.
6. Be direct and accurate - output ONLY the translated text.
"""
            },
            "anime": {
                "ollama": """
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
""",
                "openai": """
You are an anime subtitle translator. Your task:
1. ONLY translate the CURRENT text, nothing else. No warnings or explanations.
2. Preserve the exact number of lines and formatting of the original.
3. Maintain original tone and Japanese expression style.
4. Preserve anime terms, character names, and honorifics (-san, -kun, etc.).
5. Translate to Taiwan Mandarin using anime-appropriate language.
6. Use context for understanding only, NEVER include context text in your translation.
7. Output ONLY the translated text, nothing more.
"""
            },
            "movie": {
                "ollama": """
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
""",
                "openai": """
You are a movie subtitle translator. Your task:
1. ONLY translate the CURRENT text, nothing else. No explanations.
2. Preserve the exact number of lines and formatting of the original.
3. Capture the characters' emotions, slang, and dialogue style.
4. Adapt culturally specific expressions for Taiwan audience.
5. Maintain consistent character voice throughout scenes.
6. Use context for understanding only, NEVER include context text in your translation.
7. Output ONLY the translated text, nothing more.
"""
            }
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
            "last_updated": datetime.now().isoformat()
        }
        
        # 確保所有預設值都存在於配置中
        for key, value in default_values.items():
            if not self.config_manager.get_value(key, None):
                self.config_manager.set_value(key, value, auto_save=False)
        
        # 儲存配置
        self.config_manager.save_config()
    
    def _config_changed(self, config_type: str, config: Dict[str, Any]) -> None:
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
        self.custom_prompts = self.config_manager.get_value("custom_prompts", {})
        
        # 確保所有內容類型都存在
        for content_type in ["general", "adult", "anime", "movie"]:
            if content_type not in self.custom_prompts:
                self.custom_prompts[content_type] = {}
                
            # 檢查是否有對應的模板檔案
            template_file = os.path.join(self.templates_dir, f"{content_type}_template.json")
            if os.path.exists(template_file):
                try:
                    with open(template_file, 'r', encoding='utf-8') as f:
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
    
    def get_prompt(self, llm_type: str = "ollama", content_type: str = None, style: str = None) -> str:
        """根據 LLM 類型、內容類型和風格取得適合的 Prompt
        
        參數:
            llm_type: LLM類型 (如 "ollama" 或 "openai")
            content_type: 內容類型，若為None則使用當前設定
            style: 翻譯風格，若為None則使用當前設定
            
        回傳:
            提示詞文本
        """
        # 使用指定的內容類型和風格，或使用當前設定
        content_type = content_type or self.current_content_type
        style = style or self.current_style
        
        # 檢查是否有自訂提示詞
        if (content_type in self.custom_prompts and 
            llm_type in self.custom_prompts[content_type]):
            prompt = self.custom_prompts[content_type][llm_type]
        else:
            # 使用預設提示詞
            if content_type in self.default_prompts and llm_type in self.default_prompts[content_type]:
                prompt = self.default_prompts[content_type][llm_type]
            else:
                # 回退到通用提示詞
                prompt = self.default_prompts["general"].get(llm_type, 
                                                        self.default_prompts["general"]["ollama"])
        
        # 套用風格修飾符（如果不是標準風格）
        if style != "standard":
            prompt = self._apply_style_modifier(prompt, style, llm_type)
            
        # 套用語言對修飾符
        prompt = self._apply_language_pair_modifier(prompt, self.current_language_pair)
        
        return prompt.strip()
    
    def get_optimized_message(self, text: str, context_texts: List[str], llm_type: str, model_name: str) -> List[Dict[str, str]]:
        """根據不同LLM和模型生成優化的提示訊息格式
        
        參數:
            text: 要翻譯的文字
            context_texts: 上下文文本列表
            llm_type: LLM類型 (如 "ollama" 或 "openai")
            model_name: 模型名稱
            
        回傳:
            適合API請求的訊息列表
        """
        # 獲取基本提示詞
        prompt = self.get_prompt(llm_type)
        
        # 為不同的LLM類型創建不同格式的訊息
        if llm_type == "openai" or llm_type == "anthropic":
            # OpenAI/Anthropic的訊息格式
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"待翻譯文本:\n{text}\n\n上下文僅供理解參考(不要包含在翻譯中):\n{', '.join(context_texts)}"}
            ]
        else:
            # Ollama等其他LLM的訊息格式
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"待翻譯文本:\n{text}\n\n上下文僅供理解參考(不要包含在翻譯中):\n{', '.join(context_texts)}"}
            ]
        
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
                "openai": "Translate literally. Prioritize source accuracy over target fluency. Only translate the current text, never context."
            },
            "localized": {
                "ollama": "Focus on adapting the content to the target culture. Use Taiwan-specific expressions, cultural references, and idioms where appropriate to make the translation feel natural to local readers. Remember to ONLY translate the CURRENT text, not context.",
                "openai": "Translate with cultural adaptation. Use Taiwan expressions and references. Only translate the current text, never context."
            },
            "specialized": {
                "ollama": "Focus on accurate translation of terminology relevant to the content domain. Prioritize precision in specialized terms and concepts. Remember to ONLY translate the CURRENT text, not context.",
                "openai": "Translate with domain precision. Prioritize accurate terminology. Only translate the current text, never context."
            }
        }
        
        if style in style_modifiers and llm_type in style_modifiers[style]:
            modifier = style_modifiers[style][llm_type]
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
            prompt = re.sub(
                r'(Taiwan Mandarin|繁體中文|Traditional Chinese)', 
                target, 
                prompt
            )
            
            # 添加明確的語言對說明
            language_instruction = f"\nTranslate from {source} to {target}. Remember to ONLY translate the CURRENT text, not context."
            return f"{prompt}{language_instruction}"
            
        return prompt
    
    def set_prompt(self, new_prompt: str, llm_type: str = "ollama", content_type: str = None) -> bool:
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
            "version": len(self.version_history[content_type][llm_type]) + 1
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
            
            with open(template_file, 'w', encoding='utf-8') as f:
                json.dump(self.custom_prompts[content_type], f, ensure_ascii=False, indent=4)
            logger.debug(f"已儲存模板至: {template_file}")
            return True
        except Exception as e:
            logger.error(f"儲存模板檔案時發生錯誤: {format_exception(e)}")
            return False
    
    def get_version_history(self, content_type: str = None, llm_type: str = None) -> List[Dict[str, Any]]:
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
            return self.version_history[content_type].get(llm_type, [])
            
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
        if (content_type in self.version_history and 
            llm_type in self.version_history[content_type] and
            0 <= version_index < len(self.version_history[content_type][llm_type])):
            
            # 取得要恢復的版本
            version = self.version_history[content_type][llm_type][version_index]
            
            # 設置提示詞
            self.set_prompt(version["prompt"], llm_type, content_type)
            
            logger.info(f"已恢復 '{content_type}' 類型的 '{llm_type}' 提示詞到版本 {version['version']}")
            return True
            
        logger.warning(f"無法恢復版本，找不到對應的版本記錄")
        return False
    
    def reset_to_default(self, llm_type: str = None, content_type: str = None) -> bool:
        """重置為預設提示詞
        
        參數:
            llm_type: LLM類型，若為None則重置所有LLM類型
            content_type: 內容類型，若為None則使用當前設定
            
        回傳:
            是否重置成功
        """
        content_type = content_type or self.current_content_type
        
        if llm_type:
            # 重置特定 LLM 類型的提示詞
            if content_type in self.default_prompts and llm_type in self.default_prompts[content_type]:
                self.set_prompt(self.default_prompts[content_type][llm_type], llm_type, content_type)
                logger.info(f"已重置 '{content_type}' 類型的 '{llm_type}' 提示詞為預設值")
                return True
        else:
            # 重置所有 LLM 類型的提示詞
            success = True
            for llm in ["ollama", "openai"]:
                if content_type in self.default_prompts and llm in self.default_prompts[content_type]:
                    result = self.set_prompt(self.default_prompts[content_type][llm], llm, content_type)
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
        if content_type in ["general", "adult", "anime", "movie"]:
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
    
    def get_available_content_types(self) -> List[str]:
        """取得可用的內容類型
        
        回傳:
            內容類型列表
        """
        return ["general", "adult", "anime", "movie"]
    
    def get_available_styles(self) -> Dict[str, str]:
        """取得可用的翻譯風格
        
        回傳:
            翻譯風格字典 {風格代碼: 風格描述}
        """
        return self.translation_styles
    
    def get_available_language_pairs(self) -> List[str]:
        """取得可用的語言對
        
        回傳:
            語言對列表
        """
        return list(self.language_pairs.keys())
    
    def export_prompt(self, content_type: str = None, llm_type: str = None, file_path: str = None) -> Optional[str]:
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
            "metadata": {
                "exported_at": datetime.now().isoformat(),
                "content_type": content_type,
                "version": "1.0"
            },
            "prompts": {}
        }
        
        if llm_type:
            # 匯出特定 LLM 的提示詞
            if content_type in self.custom_prompts and llm_type in self.custom_prompts[content_type]:
                export_data["prompts"][llm_type] = self.custom_prompts[content_type][llm_type]
            else:
                # 使用預設提示詞
                export_data["prompts"][llm_type] = self.default_prompts[content_type].get(llm_type, "")
        else:
            # 匯出所有 LLM 的提示詞
            for llm in ["ollama", "openai"]:
                if content_type in self.custom_prompts and llm in self.custom_prompts[content_type]:
                    export_data["prompts"][llm] = self.custom_prompts[content_type][llm]
                else:
                    # 使用預設提示詞
                    export_data["prompts"][llm] = self.default_prompts[content_type].get(llm, "")
        
        # 生成輸出檔案路徑
        if not file_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name = f"prompt_export_{content_type}_{timestamp}.json"
            file_path = os.path.join(self.templates_dir, file_name)
            
        try:
            # 確保目錄存在
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            with open(file_path, 'w', encoding='utf-8') as f:
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
                
            with open(input_path, 'r', encoding='utf-8') as f:
                import_data = json.load(f)
            
            # 驗證匯入資料格式
            if not all(k in import_data for k in ["metadata", "prompts"]):
                logger.warning(f"無效的提示詞匯入格式: {input_path}")
                return False
                
            content_type = import_data["metadata"].get("content_type", "general")
            
            # 匯入提示詞
            for llm_type, prompt in import_data["prompts"].items():
                if llm_type not in ["ollama", "openai"]:
                    logger.warning(f"跳過不支援的LLM類型: {llm_type}")
                    continue
                self.set_prompt(prompt, llm_type, content_type)
                
            logger.info(f"已從 {input_path} 匯入 '{content_type}' 類型的提示詞")
            return True
        except Exception as e:
            logger.error(f"匯入提示詞時發生錯誤: {format_exception(e)}")
            return False

    def analyze_prompt(self, prompt: str) -> Dict[str, Any]:
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
            "quality_score": 0
        }
        # 檢測是否包含規則
        if re.search(r'(rule|guidelines|follow these|instructions|請遵守)', prompt, re.IGNORECASE):
            analysis["contains_rules"] = True
            analysis["clarity"] += 1
            
        # 檢測是否包含例子
        if re.search(r'(example|for instance|such as|舉例|例如)', prompt, re.IGNORECASE):
            analysis["contains_examples"] = True
            analysis["specificity"] += 1
            
        # 檢測是否包含約束條件
        if re.search(r'(only|must|should|do not|avoid|禁止|不要|必須)', prompt, re.IGNORECASE):
            analysis["contains_constraints"] = True
            analysis["completeness"] += 1
            
        # 檢測格式化程度
        if prompt.count('\n') > 3:
            analysis["formatting_score"] += 1
            
        if re.search(r'(\d+\.|\*|-|\d+\))', prompt):
            analysis["formatting_score"] += 1
            
        # 計算總體得分
        analysis["clarity"] += min(3, prompt.count('.') // 3)
        analysis["specificity"] += min(3, len(re.findall(r'\b(translate|翻譯|maintain|保持|preserve|keep|確保)\b', prompt, re.IGNORECASE)))
        analysis["completeness"] += min(3, len(re.findall(r'\b(tone|style|context|語氣|風格|上下文)\b', prompt, re.IGNORECASE)))
            
        # 調整分數範圍 (0-5)
        for key in ["clarity", "specificity", "completeness", "formatting_score"]:
            analysis[key] = min(5, analysis[key])
            
        # 計算總體品質得分 (0-100)
        analysis["quality_score"] = (
            (analysis["clarity"] * 20) +
            (analysis["specificity"] * 20) +
            (analysis["completeness"] * 20) +
            (analysis["formatting_score"] * 10) +
            (30 if analysis["contains_rules"] and analysis["contains_constraints"] else 0)
        ) // 5
            
        return analysis