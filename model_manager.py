# model_manager.py
import json
import urllib.request
from typing import List, Dict
import time
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

class ModelManager:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.default_model = "huihui_ai/aya-expanse-abliterated:latest"
        self.model_patterns = [
            'llama', 'mixtral', 'aya', 'yi', 'qwen', 'solar',
            'mistral', 'openchat', 'neural', 'phi', 'stable',
            'dolphin', 'vicuna', 'zephyr', 'gemma', 'deepseek'
        ]
        # 模型列表緩存
        self.cached_models = {}
        self.cache_time = {}
        self.cache_expiry = 600  # 10分鐘緩存過期

    def get_model_list(self, llm_type: str, api_key: str = None) -> List[str]:
        """根據 LLM 類型獲取模型列表，使用緩存提高速度"""
        # 檢查緩存是否有效
        if llm_type in self.cached_models:
            elapsed = time.time() - self.cache_time.get(llm_type, 0)
            if elapsed < self.cache_expiry:
                return self.cached_models[llm_type]

        # 重新獲取模型列表
        if llm_type == "ollama":
            models = self._get_ollama_models()
        elif llm_type == "openai":
            models = self._get_openai_models(api_key)
        else:
            models = [self.default_model]  # 默認回退

        # 更新緩存
        self.cached_models[llm_type] = models
        self.cache_time[llm_type] = time.time()
        return models

    def _get_ollama_models(self) -> List[str]:
        """獲取 Ollama 模型列表，改進檢測邏輯"""
        try:
            models = set()
            
            # 嘗試使用 /api/tags 端點
            try:
                req = urllib.request.Request(f"{self.base_url}/api/tags")
                req.add_header('User-Agent', 'SRT Translator/1.0')
                
                with urllib.request.urlopen(req, timeout=5) as response:
                    result = json.loads(response.read().decode('utf-8'))
                    
                    # 處理不同 API 版本可能的格式
                    if isinstance(result.get('models'), list):
                        for model in result['models']:
                            if isinstance(model, dict) and 'name' in model:
                                models.add(model['name'])
                    elif 'models' in result and isinstance(result['models'], dict):
                        # 某些版本可能使用字典格式
                        for model_name in result['models'].keys():
                            models.add(model_name)
                    
                    # 如果 models 不是預期格式，檢查頂層結構
                    if len(models) == 0 and isinstance(result, list):
                        for item in result:
                            if isinstance(item, dict) and 'name' in item:
                                models.add(item['name'])
            except Exception as e:
                logger.warning(f"/api/tags 端點獲取失敗: {str(e)}")
                    
            # 如果 /api/tags 未獲取到足夠模型，嘗試 /api/show
            if len(models) < 2:
                try:
                    req = urllib.request.Request(f"{self.base_url}/api/show")
                    req.add_header('User-Agent', 'SRT Translator/1.0')
                    
                    with urllib.request.urlopen(req, timeout=5) as response:
                        result = json.loads(response.read().decode('utf-8'))
                        
                        if isinstance(result, list):
                            for model in result:
                                if isinstance(model, dict) and 'name' in model:
                                    models.add(model['name'])
                        elif isinstance(result, dict) and 'models' in result:
                            for model_name in result['models']:
                                models.add(model_name)
                except Exception as e:
                    logger.warning(f"/api/show 端點獲取失敗: {str(e)}")
            
            # 如果還是沒有結果，嘗試一些其他端點
            if len(models) < 2:
                try:
                    req = urllib.request.Request(f"{self.base_url}/api/list")
                    req.add_header('User-Agent', 'SRT Translator/1.0')
                    
                    with urllib.request.urlopen(req, timeout=5) as response:
                        result = json.loads(response.read().decode('utf-8'))
                        if isinstance(result, list):
                            for item in result:
                                if isinstance(item, dict) and 'name' in item:
                                    models.add(item['name'])
                        elif isinstance(result, dict) and 'models' in result:
                            for model_name in result['models']:
                                if isinstance(model_name, str):
                                    models.add(model_name)
                except Exception as e:
                    logger.warning(f"/api/list 端點獲取失敗: {str(e)}")
            
            # 確保至少有默認模型
            models.add(self.default_model)
            
            # 現在過濾模型，但標準放寬 - 僅當有大量模型時才應用過濾
            model_list = list(models)
            if len(model_list) > 10:  # 只有模型很多時才過濾
                filtered_models = [m for m in model_list if any(pattern in m.lower() for pattern in self.model_patterns)]
                # 如果過濾後太少，就還是用原來的列表
                if len(filtered_models) >= 3:
                    model_list = filtered_models
            
            # 排序模型列表
            model_list = sorted(model_list)
            
            # 確保默認模型在首位
            if self.default_model in model_list:
                model_list.remove(self.default_model)
                model_list.insert(0, self.default_model)
            
            logger.info(f"檢測到 {len(model_list)} 個 Ollama 模型")
            return model_list if model_list else [self.default_model]
                
        except Exception as e:
            logger.error(f"獲取 Ollama 模型列表時發生錯誤: {str(e)}")
            return [self.default_model]

    def _get_openai_models(self, api_key: str) -> List[str]:
        """獲取 OpenAI 模型列表並按翻譯效能排序"""
        if not api_key:
            logger.warning("未提供 OpenAI API Key，返回預設模型")
            return ["gpt-3.5-turbo"]
        
        try:
            client = OpenAI(api_key=api_key)
            models = client.models.list()
            
            # 優先推薦適合翻譯的模型
            translation_priority = {
                "gpt-4o": 1,             # 最新、最強大，但最貴
                "gpt-4-turbo": 2,        # 強大但貴
                "gpt-4": 3,              # 強大但貴
                "gpt-3.5-turbo-16k": 4,  # 上下文較大，適合較長字幕
                "gpt-3.5-turbo": 5,      # 經濟實惠，適合大多數翻譯
                "gpt-4-vision-preview": 999  # 不推薦用於普通翻譯
            }
            
            model_list = []
            for model in models:
                if "gpt" in model.id and not model.id.endswith("0301") and not model.id.endswith("0613"):
                    model_list.append(model.id)
            
            # 按翻譯優先級排序
            sorted_models = sorted(model_list, key=lambda m: translation_priority.get(m, 900))
            
            # 確保列表中有最常用的模型
            for default_model in ["gpt-3.5-turbo", "gpt-4"]:
                if default_model not in sorted_models:
                    sorted_models.append(default_model)
                    
            return sorted_models
        except Exception as e:
            logger.error(f"獲取 OpenAI 模型列表時發生錯誤: {str(e)}")
            return ["gpt-3.5-turbo"]

    def get_default_model(self, llm_type: str) -> str:
        """返回預設模型，針對翻譯進行優化"""
        if llm_type == "openai":
            return "gpt-3.5-turbo"  # 最經濟的選擇
        return self.default_model
    
    def get_model_info(self, model_name: str) -> Dict[str, any]:
        """獲取模型的詳細資訊和使用建議"""
        model_info = {
            # OpenAI 模型
            "gpt-4o": {
                "description": "OpenAI 最強大的翻譯模型，速度快且精確",
                "pricing": "高",
                "recommended_for": "專業翻譯，需要最高質量",
                "parallel": 20
            },
            "gpt-4-turbo": {
                "description": "強大的翻譯模型，適合需要高質量翻譯的場合",
                "pricing": "高",
                "recommended_for": "專業翻譯，需要高質量",
                "parallel": 15
            },
            "gpt-4": {
                "description": "強大而穩定的翻譯模型",
                "pricing": "高",
                "recommended_for": "專業翻譯，需要高質量",
                "parallel": 10
            },
            "gpt-3.5-turbo-16k": {
                "description": "具有較大上下文窗口的翻譯模型",
                "pricing": "中",
                "recommended_for": "包含較多上下文的翻譯",
                "parallel": 25
            },
            "gpt-3.5-turbo": {
                "description": "平衡經濟性和翻譯質量的模型",
                "pricing": "低",
                "recommended_for": "日常翻譯，最具成本效益",
                "parallel": 30
            }
        }
        
        return model_info.get(model_name, {
            "description": "未知模型",
            "pricing": "未知",
            "recommended_for": "通用用途",
            "parallel": 10
        })

# 測試代碼
if __name__ == "__main__":
    try:
        with open("openapi_api_key.txt", "r") as f:
            api_key = f.read().strip()
        manager = ModelManager()
        print("Ollama 模型:", manager.get_model_list("ollama"))
        print("OpenAI 模型:", manager.get_model_list("openai", api_key))
    except Exception as e:
        print(f"測試時發生錯誤: {str(e)}")