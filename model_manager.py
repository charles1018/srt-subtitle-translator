# model_manager.py
import json
import urllib.request
from typing import List

class ModelManager:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.default_model = "huihui_ai/aya-expanse-abliterated:latest"
        self.model_patterns = [
            'llama', 'mixtral', 'aya', 'yi', 'qwen', 'solar',
            'mistral', 'openchat', 'neural', 'phi', 'stable',
            'dolphin', 'vicuna', 'zephyr', 'gemma', 'deepseek'
        ]

    def get_model_list(self) -> List[str]:
        """獲取可用的模型列表"""
        try:
            # 嘗試使用 /api/tags 獲取模型列表
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                models = set()  # 使用集合避免重複
                
                # 處理 tags API 返回的數據
                if isinstance(result.get('models'), list):
                    for model in result['models']:
                        if isinstance(model, dict) and 'name' in model:
                            model_name = model['name']
                            if any(pattern in model_name.lower() for pattern in self.model_patterns):
                                models.add(model_name)
                
                # 如果模型數量不足，嘗試使用 /api/show
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
                
                # 確保預設模型存在
                models.add(self.default_model)
                
                # 轉換為排序後的列表，預設模型放在首位
                model_list = sorted(list(models))
                if self.default_model in model_list:
                    model_list.remove(self.default_model)
                    model_list.insert(0, self.default_model)
                
                return model_list if model_list else [self.default_model]
                
        except Exception as e:
            print(f"獲取模型列表時發生錯誤: {str(e)}")
            return [self.default_model]

    def get_default_model(self) -> str:
        """返回預設模型"""
        return self.default_model

# 測試代碼
if __name__ == "__main__":
    manager = ModelManager()
    models = manager.get_model_list()
    print("可用模型列表:")
    for model in models:
        print(f"- {model}")
    print(f"預設模型: {manager.get_default_model()}")