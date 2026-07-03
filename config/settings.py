"""Smart BI Agent - Core Configuration"""
import os
from dataclasses import dataclass, field

@dataclass
class LLMConfig:
    api_key: str = os.getenv("SILICONFLOW_API_KEY", "")
    base_url: str = "https://api.siliconflow.cn/v1"
    model: str = "Qwen/Qwen2.5-7B-Instruct"
    temperature: float = 0.1
    max_tokens: int = 2048
    use_local: bool = True
    local_model: str = "qwen2.5:7b"
    local_base_url: str = "http://localhost:11434/v1"

@dataclass
class DatabaseConfig:
    db_path: str = "data/demo_erp.db"

@dataclass
class AgentConfig:
    few_shot_k: int = 3
    max_retries: int = 2
    sql_timeout: int = 10
    enable_self_correction: bool = True
    similarity_threshold: float = 0.75

@dataclass
class AppConfig:
    app_name: str = "Smart BI Agent"
    version: str = "1.0.0"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000
    llm: LLMConfig = field(default_factory=LLMConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)

CONFIG = AppConfig()
