"""
配置管理
统一管理环境变量和配置项
"""
import os
from pathlib import Path
from typing import Optional
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__) # 获取当前模块的 logger

load_dotenv()

# ==================== 路径配置 ====================
PROJECT_ROOT = Path(__file__).parent.parent.parent
BASE_DIR = PROJECT_ROOT  # 别名，供其他模块使用
PERSONAS_DIR = PROJECT_ROOT / "src" / "app" / "prompts" / "personas"
MEMORY_FILE = PROJECT_ROOT / "memory_store.json"


# ==================== 环境变量 ====================
def get_env(key: str, default: Optional[str] = None) -> str:
    """获取环境变量"""
    return os.getenv(key, default)


# # ==================== LLM 配置 ====================
# def get_llm_model():
#     """获取 LLM 模型实例"""
#     from langchain_google_vertexai import ChatVertexAI, HarmBlockThreshold, HarmCategory
#
#     model_name = get_env("LLM_MODEL", "gemini-2.0-flash-exp")
#     temperature = float(get_env("LLM_TEMPERATURE", "0.7"))
#
#     return ChatVertexAI(
#         model_name=model_name,
#         temperature=temperature,
#         max_output_tokens=2048,
#         safety_settings={
#             HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
#             HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
#             HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
#             HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
#         },
#     )

def get_llm_model():
    """
    获取 LLM 模型实例
    """
    api_key = os.getenv("API_KEY")
    base_url = os.getenv("BASE_URL")
    model_name = os.getenv("CHAT_MODEL")

    if not api_key:
        raise ValueError("未找到 API_KEY，请检查 .env 文件")

    logger.info(f"正在初始化 LLM 模型: [{model_name}] (Base URL: {base_url})")

    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=0.7,
        streaming=False # 根据需要开启
    )


# ==================== 人设配置 ====================
def get_system_prompt() -> str:
    """
    获取当前人设的系统提示词
    通过环境变量 PERSONA_NAME 指定
    """
    from app.memory.persona_loader import load_persona_from_env
    
    return load_persona_from_env(default="youci")


# ==================== Google Cloud 配置 ====================
GOOGLE_CLOUD_PROJECT = get_env("GOOGLE_CLOUD_PROJECT")
GOOGLE_APPLICATION_CREDENTIALS = get_env("GOOGLE_APPLICATION_CREDENTIALS")


# ==================== 记忆配置 ====================
MEMORY_MAX_ITEMS = int(get_env("MEMORY_MAX_ITEMS", "10"))


# ==================== API 配置 ====================
LANGGRAPH_API_PORT = int(get_env("LANGGRAPH_API_PORT", "2024"))
LANGGRAPH_API_HOST = get_env("LANGGRAPH_API_HOST", "0.0.0.0")

def get_redis_config():
    """获取 Redis 连接配置"""
    return {
        "host": os.getenv("REDIS_HOST", "localhost"),
        "port": int(os.getenv("REDIS_PORT", 6379)),
        "db": int(os.getenv("REDIS_DB", 0)),
        "password": os.getenv("REDIS_PASSWORD", None),
        "decode_responses": True
    }