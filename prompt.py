import json
import os
import logging
import re
import time
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path
import logging.handlers

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
    def __init__(self, config_file: str = "config/prompt_config.json"):
        self.config_file = config_file
        self.config_dir = os.path.dirname(config_file) or "."
        self.templates_dir = os.path.join(self.config_dir, "prompt_templates")
        
        # 確保模板目錄存在
        os.makedirs(self.templates_dir, exist_ok=True)
        
        # 翻譯風格定義
        self.translation_styles = {
            "standard": "標準翻譯 - 平衡準確性和自然度",
            "literal": "直譯 - 更忠於原文的字面意思",
            "literary": "文學翻譯 - 更優美的表達",
            "localized": "本地化翻譯 - 更適合目標語言文化",
            "concise": "簡潔翻譯 - 更精簡的表達",
            "formal": "正式翻譯 - 更正式的語氣",
            "casual": "口語化翻譯 - 更口語化的表達",
            "specialized": "專業翻譯 - 針對特定領域"
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
        
        # 預設提示詞 (通用)
        self.default_prompts = {
            "general": {
                "ollama": """
You are a professional translator. Your task is to translate subtitles accurately.
Please strictly follow these rules:
1. Only output the translated text without any additional response.
2. Maintain the original tone and expression style.
3. Use context (surrounding subtitles) to ensure accurate and consistent translation.
4. Keep ellipses (...) if present in the original text.
5. Translate into natural Taiwan Mandarin Chinese expressions.
6. Do not output any content other than the translation.
""",
                "openai": """
You are a high-efficiency subtitle translator. Your task:
1. ONLY output the translated text. No warnings, explanations, or quotes.
2. Maintain original tone and style. Translate to Taiwan Mandarin.
3. Keep context-appropriate. Preserve ellipses (...) and technical terms when appropriate.
4. Optimize for efficiency and accuracy. Be concise.
"""
            },
            "adult": {
                "ollama": """
You are a professional translator for adult video subtitles. 
Please strictly follow these rules:
1. Only output the translated text without any additional response.
2. Maintain the original tone and expression style.
3. Use context (surrounding subtitles) to ensure accurate and consistent translation.
4. Translate into natural Taiwan Mandarin Chinese expressions with appropriate adult terminology.
5. Keep ellipses (...) if present in the original text.
6. Do not output any warnings, explanations, or commentary about the content.
""",
                "openai": """
You are a high-efficiency adult content subtitle translator. Your task:
1. ONLY output the translated text. No warnings, explanations, or quotes.
2. Maintain original tone and style. Translate to Taiwan Mandarin.
3. Use appropriate adult terminology in the target language.
4. Keep context-appropriate. Preserve ellipses (...) when present.
5. Optimize for efficiency. Be direct and accurate.
"""
            },
            "anime": {
                "ollama": """
You are a professional anime subtitle translator.
Please strictly follow these rules:
1. Only output the translated text without any additional response.
2. Maintain the original tone and expression style.
3. Preserve anime-specific terminology, character names, and Japanese honorifics.
4. Translate into natural Taiwan Mandarin Chinese expressions that anime fans would appreciate.
5. Use context (surrounding subtitles) to ensure accurate and consistent translation.
6. Keep ellipses (...) if present in the original text.
""",
                "openai": """
You are an anime subtitle translator. Your task:
1. ONLY output the translated text. No warnings or explanations.
2. Maintain original tone and Japanese expression style.
3. Preserve anime terms, character names, and honorifics (-san, -kun, etc.).
4. Translate to Taiwan Mandarin using anime-appropriate language.
5. Keep context-appropriate. Preserve ellipses (...) when present.
"""
            },
            "documentary": {
                "ollama": """
You are a professional documentary subtitle translator.
Please strictly follow these rules:
1. Only output the translated text without any additional response.
2. Maintain accurate and precise translation of technical terms and scientific concepts.
3. Use formal and educational language appropriate for documentaries.
4. Translate into natural Taiwan Mandarin Chinese expressions.
5. Use context (surrounding subtitles) to ensure accurate and consistent translation.
6. Keep ellipses (...) if present in the original text.
""",
                "openai": """
You are a documentary subtitle translator. Your task:
1. ONLY output the translated text. No explanations.
2. Maintain precision with technical/scientific terms.
3. Use formal, educational language appropriate for Taiwan audience.
4. Keep consistent terminology throughout the context.
5. Preserve proper nouns, scientific names, and measurements appropriately.
"""
            },
            "movie": {
                "ollama": """
You are a professional movie subtitle translator.
Please strictly follow these rules:
1. Only output the translated text without any additional response.
2. Maintain the original tone, emotion, and style of dialogue.
3. Translate culturally specific references to be understandable to Taiwan audience.
4. Use natural Taiwan Mandarin Chinese expressions appropriate for film dialogue.
5. Use context (surrounding subtitles) to ensure accurate and consistent translation.
6. Keep ellipses (...) if present in the original text.
""",
                "openai": """
You are a movie subtitle translator. Your task:
1. ONLY output the translated text. No explanations.
2. Capture the characters' emotions, slang, and dialogue style.
3. Adapt culturally specific expressions for Taiwan audience.
4. Maintain consistent character voice throughout scenes.
5. Consider visual context when implied in surrounding lines.
"""
            }
        }
        
        # 載入設定
        self.config = self._load_config()
        
        # 設定當前使用的內容類型和風格
        self.current_content_type = self.config.get("current_content_type", "general")
        self.current_style = self.config.get("current_style", "standard")
        self.current_language_pair = self.config.get("current_language_pair", "日文→繁體中文")
        
        # 載入版本歷史
        self.version_history = self.config.get("version_history", {})
        
        # 載入自訂提示詞
        self._load_custom_prompts()
        
        logger.info("PromptManager 初始化完成")
    
    def _load_config(self) -> Dict[str, Any]:
        """載入主設定檔"""
        default_config = {
            "current_content_type": "general",
            "current_style": "standard",
            "current_language_pair": "日文→繁體中文",
            "custom_prompts": {},
            "version_history": {},
            "last_updated": datetime.now().isoformat()
        }
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                logger.debug(f"已載入設定檔: {self.config_file}")
                return config
            else:
                logger.info(f"設定檔不存在，使用預設設定: {self.config_file}")
                self._save_config(default_config)
                return default_config
                
        except Exception as e:
            logger.error(f"載入設定檔時發生錯誤: {str(e)}")
            return default_config
    
    def _save_config(self, config: Dict[str, Any] = None) -> None:
        """儲存設定至檔案"""
        if config is None:
            config = self.config
            
        config["last_updated"] = datetime.now().isoformat()
        
        try:
            # 確保目錄存在
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            logger.debug(f"已儲存設定至檔案: {self.config_file}")
        except Exception as e:
            logger.error(f"儲存設定檔時發生錯誤: {str(e)}")
    
    def _load_custom_prompts(self) -> None:
        """載入所有自訂提示詞"""
        # 首先從設定檔中載入已儲存的自訂提示詞
        self.custom_prompts = self.config.get("custom_prompts", {})
        
        # 然後檢查模板目錄中是否有新的模板
        for content_type in ["general", "adult", "anime", "documentary", "movie"]:
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
                    logger.error(f"載入模板檔案時發生錯誤: {str(e)}")
        
        # 更新設定
        self.config["custom_prompts"] = self.custom_prompts
        self._save_config()
    
    def get_prompt(self, llm_type: str = "ollama", content_type: str = None, style: str = None) -> str:
        """根據 LLM 類型、內容類型和風格取得適合的 Prompt"""
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
                prompt = self.default_prompts["general"][llm_type]
        
        # 套用風格修飾符（如果不是標準風格）
        if style != "standard":
            prompt = self._apply_style_modifier(prompt, style, llm_type)
            
        # 套用語言對修飾符
        prompt = self._apply_language_pair_modifier(prompt, self.current_language_pair)
        
        return prompt.strip()
    
    def _apply_style_modifier(self, prompt: str, style: str, llm_type: str) -> str:
        """根據翻譯風格修改提示詞"""
        style_modifiers = {
            "literal": {
                "ollama": "Focus on providing a more literal translation that is closer to the original text meaning. Prioritize accuracy to source text over natural flow in the target language.",
                "openai": "Translate literally. Prioritize source accuracy over target fluency."
            },
            "literary": {
                "ollama": "Focus on providing a more elegant and literary translation. You may use more expressive language and literary devices while maintaining the meaning of the original text.",
                "openai": "Translate elegantly. Use expressive language while maintaining meaning."
            },
            "localized": {
                "ollama": "Focus on adapting the content to the target culture. Use Taiwan-specific expressions, cultural references, and idioms where appropriate to make the translation feel natural to local readers.",
                "openai": "Translate with cultural adaptation. Use Taiwan expressions and references."
            },
            "concise": {
                "ollama": "Focus on providing a concise translation. Simplify complex expressions while preserving the core meaning. Aim for clarity and brevity.",
                "openai": "Translate concisely. Simplify while preserving core meaning."
            },
            "formal": {
                "ollama": "Focus on providing a formal translation. Use more formal language, avoid contractions, colloquialisms, and slang. Maintain a respectful and professional tone.",
                "openai": "Translate formally. Use proper language and avoid colloquialisms."
            },
            "casual": {
                "ollama": "Focus on providing a casual, conversational translation. Use natural everyday language, contractions, and common expressions that would be used in casual conversation.",
                "openai": "Translate casually. Use everyday language and conversational style."
            },
            "specialized": {
                "ollama": "Focus on accurate translation of terminology relevant to the content domain. Prioritize precision in specialized terms and concepts.",
                "openai": "Translate with domain precision. Prioritize accurate terminology."
            }
        }
        
        if style in style_modifiers and llm_type in style_modifiers[style]:
            modifier = style_modifiers[style][llm_type]
            # 在提示詞結尾添加風格修飾符
            return f"{prompt}\n\nAdditional instruction: {modifier}"
        
        return prompt
    
    def _apply_language_pair_modifier(self, prompt: str, language_pair: str) -> str:
        """根據語言對修改提示詞"""
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
            language_instruction = f"\nTranslate from {source} to {target}."
            return f"{prompt}{language_instruction}"
            
        return prompt
    
    def set_prompt(self, new_prompt: str, llm_type: str = "ollama", content_type: str = None):
        """設置特定 LLM 和內容類型的提示詞"""
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
        
        # 更新設定
        self.config["custom_prompts"] = self.custom_prompts
        self._save_config()
        
        # 儲存至模板檔案
        self._save_prompt_template(content_type)
        
        logger.info(f"已設置 '{content_type}' 類型的 '{llm_type}' 提示詞")
    
    def _add_to_version_history(self, content_type: str, llm_type: str, prompt: str) -> None:
        """將提示詞添加到版本歷史"""
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
            
        # 更新設定
        self.config["version_history"] = self.version_history
        self._save_config()
    
    def _save_prompt_template(self, content_type: str) -> None:
        """儲存提示詞模板至檔案"""
        template_file = os.path.join(self.templates_dir, f"{content_type}_template.json")
        try:
            with open(template_file, 'w', encoding='utf-8') as f:
                json.dump(self.custom_prompts[content_type], f, ensure_ascii=False, indent=4)
            logger.debug(f"已儲存模板至: {template_file}")
        except Exception as e:
            logger.error(f"儲存模板檔案時發生錯誤: {str(e)}")
    
    def get_version_history(self, content_type: str = None, llm_type: str = None) -> List[Dict[str, Any]]:
        """取得提示詞的版本歷史"""
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
        """恢復到特定版本的提示詞"""
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
    
    def reset_to_default(self, llm_type: str = None, content_type: str = None):
        """重置為預設提示詞"""
        content_type = content_type or self.current_content_type
        
        if llm_type:
            # 重置特定 LLM 類型的提示詞
            if content_type in self.default_prompts and llm_type in self.default_prompts[content_type]:
                self.set_prompt(self.default_prompts[content_type][llm_type], llm_type, content_type)
                logger.info(f"已重置 '{content_type}' 類型的 '{llm_type}' 提示詞為預設值")
        else:
            # 重置所有 LLM 類型的提示詞
            for llm in ["ollama", "openai"]:
                if content_type in self.default_prompts and llm in self.default_prompts[content_type]:
                    self.set_prompt(self.default_prompts[content_type][llm], llm, content_type)
            logger.info(f"已重置 '{content_type}' 類型的所有提示詞為預設值")
    
    def set_content_type(self, content_type: str) -> None:
        """設置當前使用的內容類型"""
        if content_type in ["general", "adult", "anime", "documentary", "movie"]:
            self.current_content_type = content_type
            self.config["current_content_type"] = content_type
            self._save_config()
            logger.info(f"已設置當前內容類型為: {content_type}")
    
    def set_translation_style(self, style: str) -> None:
        """設置當前使用的翻譯風格"""
        if style in self.translation_styles:
            self.current_style = style
            self.config["current_style"] = style
            self._save_config()
            logger.info(f"已設置當前翻譯風格為: {style}")
    
    def set_language_pair(self, language_pair: str) -> None:
        """設置當前使用的語言對"""
        if language_pair in self.language_pairs:
            self.current_language_pair = language_pair
            self.config["current_language_pair"] = language_pair
            self._save_config()
            logger.info(f"已設置當前語言對為: {language_pair}")
    
    def get_available_content_types(self) -> List[str]:
        """取得可用的內容類型"""
        return ["general", "adult", "anime", "documentary", "movie"]
    
    def get_available_styles(self) -> Dict[str, str]:
        """取得可用的翻譯風格"""
        return self.translation_styles
    
    def get_available_language_pairs(self) -> List[str]:
        """取得可用的語言對"""
        return list(self.language_pairs.keys())
    
    def export_prompt(self, content_type: str = None, llm_type: str = None, file_path: str = None) -> Optional[str]:
        """匯出提示詞至檔案"""
        content_type = content_type or self.current_content_type
        
        # 要匯出的資料
        export_data = {
            "metadata": {
                "exported_at": datetime.now().isoformat(),
                "content_type": content_type
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
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=4)
            logger.info(f"已匯出提示詞至: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"匯出提示詞時發生錯誤: {str(e)}")
            return None
    
    def import_prompt(self, file_path: str) -> bool:
        """從檔案匯入提示詞"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                import_data = json.load(f)
                
            if "metadata" not in import_data or "prompts" not in import_data:
                logger.warning(f"無效的提示詞匯入格式: {file_path}")
                return False
                
            content_type = import_data["metadata"].get("content_type", "general")
            
            # 匯入提示詞
            for llm_type, prompt in import_data["prompts"].items():
                self.set_prompt(prompt, llm_type, content_type)
                
            logger.info(f"已從 {file_path} 匯入 '{content_type}' 類型的提示詞")
            return True
        except Exception as e:
            logger.error(f"匯入提示詞時發生錯誤: {str(e)}")
            return False
    
    def get_optimized_message(self, text: str, context_texts: List[str], llm_type: str, model_name: str) -> List[Dict[str, str]]:
        """生成為特定 LLM 和模型優化的訊息結構"""
        # 取得適合當前設置的系統提示詞
        system_prompt = self.get_prompt(llm_type)
        
        # 為不同的 LLM 優化訊息結構
        if llm_type == "openai":
            # 為 OpenAI 優化上下文處理和格式
            # 精簡上下文，減少 token 使用
            limited_context = []
            
            # 只包含非空的上下文，最多 6 行
            for ctx in context_texts:
                if ctx.strip():
                    limited_context.append(ctx)
                    if len(limited_context) >= 6:
                        break
            
            # 構建更緊湊的使用者提示
            user_content = "上下文：\n" + "\n".join(limited_context)
            user_content += f"\n\n翻譯：{text}"
            
            # GPT-4 等高級模型可以處理更簡潔的指令
            if "gpt-4" in model_name:
                return [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ]
            else:
                # 較低階模型可能需要更明確的指令
                return [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ]
                
        elif llm_type == "anthropic":
            # 為 Anthropic Claude 模型優化
            # Claude 模型更喜歡詳細的上下文和指令
            user_content = "以下是字幕內容（提供上下文參考）：\n\n"
            
            # 提供帶序號的上下文
            for i, ctx in enumerate(context_texts):
                if ctx.strip():
                    user_content += f"[{i+1}] {ctx}\n"
            
            user_content += f"\n請將當前字幕翻譯（保持原始語氣和風格）：\n{text}"
            
            return [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]
            
        else:
            # 標準 Ollama 格式（或其他開源模型）
            return [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"以下是字幕內容（提供前後作為上下文參考）：\n{json.dumps(context_texts, ensure_ascii=False)}\n請將當前字幕翻譯：\n'{text}'"}
            ]
    
    def get_full_message(self, text: str, context_texts: List[str]) -> List[Dict[str, str]]:
        """生成完整的訊息結構，供翻譯使用 (保留向後相容性)"""
        return self.get_optimized_message(text, context_texts, "ollama", "default")
    
    def add_custom_content_type(self, content_type: str, prompts: Dict[str, str]) -> bool:
        """添加自訂內容類型的提示詞"""
        if content_type in self.get_available_content_types():
            logger.warning(f"內容類型 '{content_type}' 已存在")
            return False
            
        # 添加到自訂提示詞
        self.custom_prompts[content_type] = prompts
        
        # 更新設定
        self.config["custom_prompts"] = self.custom_prompts
        self._save_config()
        
        # 儲存至模板檔案
        self._save_prompt_template(content_type)
        
        logger.info(f"已添加自訂內容類型: {content_type}")
        return True
    
    def get_prompt_statistics(self) -> Dict[str, Any]:
        """取得提示詞使用統計資訊"""
        stats = {
            "content_types": len(self.custom_prompts),
            "total_prompts": sum(len(prompts) for prompts in self.custom_prompts.values()),
            "current_content_type": self.current_content_type,
            "current_style": self.current_style,
            "current_language_pair": self.current_language_pair,
            "version_history_entries": sum(
                len(history) for content_type in self.version_history.values() 
                for history in content_type.values()
            ),
            "last_updated": self.config.get("last_updated"),
            "content_type_details": {}
        }
        
        # 添加各內容類型的詳細資訊
        for content_type, prompts in self.custom_prompts.items():
            stats["content_type_details"][content_type] = {
                "llm_types": list(prompts.keys()),
                "has_openai": "openai" in prompts,
                "has_ollama": "ollama" in prompts,
                "prompt_lengths": {
                    llm: len(prompt) for llm, prompt in prompts.items()
                }
            }
            
        return stats
    
    def analyze_prompt(self, prompt: str) -> Dict[str, Any]:
        """分析提示詞的品質和特性"""
        analysis = {
            "length": len(prompt),
            "word_count": len(prompt.split()),
            "clarity": 0,
            "specificity": 0,
            "completeness": 0,
            "contains_rules": False,
            "contains_examples": False,
            "contains_constraints": False,
            "formatting_score": 0
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

# 測試代碼
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # 初始化 PromptManager
    manager = PromptManager()
    
    print("\n==== 提示詞管理器測試 ====")
    
    # 測試取得不同類型的提示詞
    print("\n測試取得提示詞:")
    for content_type in manager.get_available_content_types():
        print(f"\n{content_type} 類型 (OpenAI):")
        prompt = manager.get_prompt("openai", content_type)
        print(prompt[:100] + "..." if len(prompt) > 100 else prompt)
    
    # 測試不同風格
    print("\n測試不同翻譯風格:")
    for style in ["standard", "literary", "localized"]:
        print(f"\n{style} 風格:")
        prompt = manager.get_prompt("ollama", "general", style)
        print(prompt[:100] + "..." if len(prompt) > 100 else prompt)
        
    # 測試取得優化訊息結構
    print("\n測試取得優化訊息結構:")
    text = "こんにちは、元気ですか？"
    context = ["前の字幕です。", "こんにちは、元気ですか？", "次の字幕です。"]
    messages = manager.get_optimized_message(text, context, "openai", "gpt-3.5-turbo")
    for msg in messages:
        print(f"{msg['role']}: {msg['content'][:50]}...")
        
    # 測試統計功能
    print("\n測試提示詞統計:")
    stats = manager.get_prompt_statistics()
    print(f"內容類型數量: {stats['content_types']}")
    print(f"提示詞總數: {stats['total_prompts']}")
    print(f"當前內容類型: {stats['current_content_type']}")
    print(f"當前翻譯風格: {stats['current_style']}")
    
    # 測試提示詞分析
    print("\n測試提示詞分析:")
    sample_prompt = """
    You are a professional translator. Please follow these rules:
    1. Only output the translated text.
    2. Maintain the original tone and style.
    3. Use natural expressions in the target language.
    4. Use context to ensure consistency.
    """
    analysis = manager.analyze_prompt(sample_prompt)
    print(f"提示詞長度: {analysis['length']}")
    print(f"清晰度得分: {analysis['clarity']}/5")
    print(f"特異性得分: {analysis['specificity']}/5")
    print(f"完整性得分: {analysis['completeness']}/5")
    print(f"總體品質得分: {analysis['quality_score']}/100")