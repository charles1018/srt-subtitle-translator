# prompt.py
import json
from typing import List, Optional

class PromptManager:
    def __init__(self, config_file: str = "prompt_config.json"):
        self.config_file = config_file
        # 預設提示 (通用)
        self.default_prompt = """
You are a professional translator for 日本A片字幕檔(影片類型主要是亂倫、性交、虐待、凌辱、變態等非正常影片)。
請嚴格遵守以下規則：
1. 只輸出翻譯後的文本，不要有任何其他回應(不要有開場白，不要輸出警告，也不要有任何的解釋)，內容前後不要有"「"、"」"。
2. 保持原文的語氣和表達方式。
3. 根據提供的上下文（前後五句字幕）並考量保留常見英文專有名詞,確保翻譯準確且符合台灣的表達習慣。
4. 內容轉換成台灣人習慣的說法,可依語境增加在地化元素,重點是要讓台灣讀者覺得貼近生活。
5. 如果看到省略號(...)，保留在譯文中。
6. 禁止輸出任何非翻譯內容。
"""
        # 為 OpenAI 優化的精簡提示
        self.openai_prompt = """
You are a high-efficiency subtitle translator for adult videos. Your task:
1. ONLY output the translated text. No warnings, explanations, or quotes.
2. Maintain original tone and style. Translate to Taiwan Mandarin.
3. Keep context-appropriate. Preserve ellipses (...) and English terms when appropriate.
4. Optimize for efficiency and accuracy. Be concise.
"""
        self.load_custom_prompt()

    def load_custom_prompt(self):
        """從配置文件加載自定義 Prompt，若無則使用預設值"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self.custom_prompt = config.get("prompt", self.default_prompt)
                self.custom_openai_prompt = config.get("openai_prompt", self.openai_prompt)
        except FileNotFoundError:
            self.custom_prompt = self.default_prompt
            self.custom_openai_prompt = self.openai_prompt
            self.save_custom_prompt()

    def save_custom_prompt(self):
        """將當前 Prompt 保存到配置文件"""
        config = {
            "prompt": self.custom_prompt,
            "openai_prompt": self.custom_openai_prompt
        }
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

    def get_prompt(self, llm_type: str = "ollama") -> str:
        """根據 LLM 類型獲取適合的 Prompt"""
        if llm_type == "openai":
            return self.custom_openai_prompt
        return self.custom_prompt

    def set_prompt(self, new_prompt: str, llm_type: str = "ollama"):
        """設置特定 LLM 的 Prompt"""
        if llm_type == "openai":
            self.custom_openai_prompt = new_prompt.strip()
        else:
            self.custom_prompt = new_prompt.strip()
        self.save_custom_prompt()

    def get_optimized_message(self, text: str, context_texts: List[str], llm_type: str, model_name: str) -> List[dict]:
        """生成為特定 LLM 和模型優化的消息結構"""
        system_prompt = self.get_prompt(llm_type)
        
        # 為 OpenAI 優化上下文處理
        if llm_type == "openai":
            # 減少上下文數量，節省 token
            limited_context = context_texts[:min(len(context_texts), 6)]
            
            # 更簡潔的用戶提示
            user_content = f"上下文：\n"
            for i, ctx in enumerate(limited_context):
                # 只加入不是空字符串的上下文
                if ctx.strip():
                    user_content += f"{ctx}\n"
            
            # 更明確的翻譯請求
            user_content += f"\n翻譯：{text}"
            
            return [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]
        else:
            # 原始 Ollama 的消息格式
            return [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"以下是字幕內容（提供前後5句作為上下文參考）：\n{json.dumps(context_texts, ensure_ascii=False)}\n請將當前字幕翻譯：\n'{text}'"}
            ]

    def reset_to_default(self, llm_type: str = None):
        """重置為預設 Prompt"""
        if llm_type == "openai":
            self.custom_openai_prompt = self.openai_prompt
        elif llm_type == "ollama":
            self.custom_prompt = self.default_prompt
        else:
            # 重置所有
            self.custom_prompt = self.default_prompt
            self.custom_openai_prompt = self.openai_prompt
        self.save_custom_prompt()

    def get_full_message(self, text: str, context_texts: List[str]) -> List[dict]:
        """生成完整的消息結構，供翻譯使用 (保留向後兼容性)"""
        return [
            {
                "role": "system",
                "content": self.get_prompt()
            },
            {
                "role": "user",
                "content": f"以下是字幕內容（提供前後5句作為上下文參考）：\n{json.dumps(context_texts, ensure_ascii=False)}\n請將當前字幕翻譯：\n'{text}'"
            }
        ]