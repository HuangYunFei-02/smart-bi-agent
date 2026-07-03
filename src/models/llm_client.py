"""
LLM Client Module
Supports multiple LLM backends: SiliconFlow, OpenAI, Local (Ollama)
"""
import os
import json
import requests
from typing import Dict, List, Optional, Generator
from dataclasses import dataclass

@dataclass
class LLMResponse:
    content: str
    usage: Dict = None
    model: str = ""
    finish_reason: str = ""

    def __post_init__(self):
        if self.usage is None:
            self.usage = {}

class LLMClient:
    def __init__(self, 
                 api_key: str = None,
                 base_url: str = "https://api.siliconflow.cn/v1",
                 model: str = "Qwen/Qwen2.5-7B-Instruct",
                 temperature: float = 0.1,
                 max_tokens: int = 2048,
                 use_local: bool = False,
                 local_model: str = "qwen2.5:7b",
                 local_base_url: str = "http://localhost:11434/v1"):

        self.api_key = api_key or os.getenv("SILICONFLOW_API_KEY", "")
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.use_local = use_local
        self.local_model = local_model
        self.local_base_url = local_base_url

        if use_local:
            self.backend = "local"
            self.active_base_url = local_base_url
            self.active_model = local_model
        elif self.api_key:
            self.backend = "api"
            self.active_base_url = base_url
            self.active_model = model
        else:
            self.backend = "local"
            self.active_base_url = local_base_url
            self.active_model = local_model
            print("[WARN] No API key provided, falling back to local model.")

    def chat(self, 
             messages: List[Dict[str, str]], 
             stream: bool = False,
             temperature: float = None,
             max_tokens: int = None) -> LLMResponse:

        temp = temperature if temperature is not None else self.temperature
        max_tok = max_tokens if max_tokens is not None else self.max_tokens

        payload = {
            "model": self.active_model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tok,
            "stream": stream
        }

        headers = {"Content-Type": "application/json"}
        if self.backend == "api" and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = requests.post(
                f"{self.active_base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            data = response.json()

            if "choices" in data and len(data["choices"]) > 0:
                choice = data["choices"][0]
                return LLMResponse(
                    content=choice["message"]["content"],
                    usage=data.get("usage", {}),
                    model=data.get("model", self.active_model),
                    finish_reason=choice.get("finish_reason", "")
                )
            else:
                return LLMResponse(content="", usage={}, finish_reason="error")

        except requests.exceptions.ConnectionError:
            if self.backend == "local":
                raise ConnectionError(
                    "Cannot connect to local LLM server. "
                    "Please ensure Ollama is running: `ollama run qwen2.5:7b`"
                )
            else:
                raise ConnectionError("Cannot connect to LLM API. Check network and API key.")
        except Exception as e:
            return LLMResponse(content=f"[ERROR] {str(e)}", usage={}, finish_reason="error")

    def chat_stream(self, messages: List[Dict[str, str]]) -> Generator[str, None, None]:
        payload = {
            "model": self.active_model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True
        }

        headers = {"Content-Type": "application/json"}
        if self.backend == "api" and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = requests.post(
                f"{self.active_base_url}/chat/completions",
                headers=headers,
                json=payload,
                stream=True,
                timeout=120
            )
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    line = line.decode("utf-8")
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            if "choices" in data and len(data["choices"]) > 0:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta:
                                    yield delta["content"]
                        except json.JSONDecodeError:
                            continue

        except Exception as e:
            yield f"[ERROR] {str(e)}"

    def test_connection(self) -> bool:
        try:
            response = self.chat([
                {"role": "user", "content": "Say OK only."}
            ])
            return "OK" in response.content or len(response.content) > 0
        except Exception:
            return False
