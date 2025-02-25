# model_manager.py
import json
import urllib.request
from typing import List
from openai import OpenAI

class ModelManager:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.default_model = "huihui_ai/aya-expanse-abliterated:latest"
        self.model_patterns = [
            'llama', 'mixtral', 'aya', 'yi', 'qwen', 'solar',
            'mistral', 'openchat', 'neural', 'phi', 'stable',
            'dolphin', 'vicuna', 'zephyr', 'gemma', 'deepseek'
        ]

    def get_model_list(self, llm_type: str, api_key: str = None) -> List[str]:
        """根據 LLM 類型獲取模型列表"""
        if llm_type == "ollama":
            return self._get_ollama_models()
        elif llm_type == "openai":
            return self._get_openai_models(api_key)
        else:
            return [self.default_model]  # 默認回退

    def _get_ollama_models(self) -> List[str]:
        """獲取 Ollama 模型列表"""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                models = set()
                
                if isinstance(result.get('models'), list):
                    for model in result['models']:
                        if isinstance(model, dict) and 'name' in model:
                            model_name = model['name']
                            if any(pattern in model_name.lower() for pattern in self.model_patterns):
                                models.add(model_name)
                
                if len(models) < 2:
                    req = urllib.request.Request(f"{self.base_url}/api/show")
                    with urllib.request.urlopen(req) as response:
                        show_result = json.loads(response.read().decode('utf-8'))
                        if isinstance(show_result, list):
                            for model in show_result:
                                if isinstance(model, dict) and 'name' in model:
                                    model_name = model['name']
                                    if any(pattern in model_name.lower() for pattern in self.model_patterns):
                                        models.add(model_name)
                
                models.add(self.default_model)
                model_list = sorted(list(models))
                if self.default_model in model_list:
                    model_list.remove(self.default_model)
                    model_list.insert(0, self.default_model)
                
                return model_list if model_list else [self.default_model]
                
        except Exception as e:
            print(f"獲取 Ollama 模型列表時發生錯誤: {str(e)}")
            return [self.default_model]

    def _get_openai_models(self, api_key: str) -> List[str]:
        """獲取 OpenAI 模型列表"""
        if not api_key:
            print("未提供 OpenAI API Key，返回預設模型")
            return ["gpt-3.5-turbo"]  # 默認模型
        
        try:
            client = OpenAI(api_key=api_key)
            models = client.models.list()
            model_list = [model.id for model in models if "gpt" in model.id]  # 過濾包含 "gpt" 的模型
            return sorted(model_list) if model_list else ["gpt-3.5-turbo"]
        except Exception as e:
            print(f"獲取 OpenAI 模型列表時發生錯誤: {str(e)}")
            return ["gpt-3.5-turbo"]

    def get_default_model(self, llm_type: str) -> str:
        """返回預設模型"""
        return "gpt-3.5-turbo" if llm_type == "openai" else self.default_model

# 測試代碼
if __name__ == "__main__":
    with open("openapi_api_key.txt", "r") as f:
        api_key = f.read().strip()
    manager = ModelManager()
    print("Ollama 模型:", manager.get_model_list("ollama"))
    print("OpenAI 模型:", manager.get_model_list("openai", api_key))