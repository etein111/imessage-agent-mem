"""简单的 LangGraph 聊天机器人示例 - 使用 Google Gemini (Vertex AI) 流式输出"""
import asyncio
import os
from pathlib import Path
from typing import Annotated, Sequence, TypedDict

import google.auth
from google.auth import exceptions as google_auth_exceptions
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_google_vertexai import ChatVertexAI, HarmBlockThreshold, HarmCategory
from langgraph.graph import StateGraph, END, add_messages

# 导入人设加载器
from persona_loader import load_persona_from_env


class ChatState(TypedDict):
    """聊天状态"""
    messages: Annotated[Sequence[BaseMessage], add_messages]


# 在模块级别初始化模型，避免每次调用都初始化（会触发阻塞调用）
_model = None
_model_lock = asyncio.Lock()


async def get_model():
    """获取或创建模型实例（延迟初始化，在异步线程中）"""
    global _model
    if _model is None:
        async with _model_lock:
            if _model is None:
                # 在单独线程中初始化模型，避免阻塞事件循环
                def _load_credentials():
                    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
                    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
                    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

                    if creds_path and Path(creds_path).exists():
                        try:
                            credentials, project_from_file = google.auth.load_credentials_from_file(
                                creds_path, scopes=scopes
                            )
                            if not project and project_from_file:
                                project = project_from_file
                            return credentials, project
                        except google_auth_exceptions.DefaultCredentialsError:
                            pass

                    credentials, project_default = google.auth.default(scopes=scopes)
                    if not project and project_default:
                        project = project_default
                    return credentials, project

                def _init_model():
                    credentials, project = _load_credentials()
                    return ChatVertexAI(
                        model_name="gemini-2.5-flash-lite",
                        temperature=0.7,
                        max_output_tokens=8192,
                        streaming=True,
                        credentials=credentials,
                        project=project,
                        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
                        # 显式禁用安全过滤，防止因审查导致的缓冲
                        safety_settings={
                            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                        },
                    )

                _model = await asyncio.to_thread(_init_model)
    return _model


# AI "云朵" 的人设提示词
# 动态加载人设（从环境变量 PERSONA_NAME 读取，默认为 yunduo）
SYSTEM_PROMPT = load_persona_from_env(default="yunduo")

async def chatbot_node(state: ChatState, config=None):
    """聊天机器人节点 - 使用 Google Gemini 流式输出"""
    # 获取模型实例（异步初始化，避免阻塞）
    model = await get_model()

    def _normalize_content(content):
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict):
                    if "text" in part:
                        parts.append(part["text"])
                    elif "input_text" in part:
                        parts.append(part["input_text"])
                    elif "content" in part:
                        parts.append(str(part["content"]))
                else:
                    parts.append(str(part))
            return "\n".join(parts)
        if content is None:
            return ""
        return str(content)

    normalized_messages: list[BaseMessage] = []
    
    # 添加系统提示词 (Persona)
    # 如果历史消息中第一个不是 SystemMessage，则添加我们的默认人设
    if not state["messages"] or not isinstance(state["messages"][0], SystemMessage):
        normalized_messages.append(SystemMessage(content=SYSTEM_PROMPT))

    for message in state["messages"]:
        text = _normalize_content(message.content)
        if isinstance(message, HumanMessage):
            normalized_messages.append(HumanMessage(content=text))
        elif isinstance(message, AIMessage):
            normalized_messages.append(AIMessage(content=text))
        elif isinstance(message, SystemMessage):
            normalized_messages.append(SystemMessage(content=text))
        elif isinstance(message, ToolMessage):
            normalized_messages.append(ToolMessage(content=text, tool_call_id=message.tool_call_id))
        else:
            normalized_messages.append(HumanMessage(content=text))
    
    # 使用 ainvoke，依赖 LangGraph 的自动流式捕获
    try:
        # 显式传递 config 是必须的，LangGraph 会注入 callback handler
        response = await model.ainvoke(normalized_messages, config=config)
        return {"messages": [response]}

    except Exception as e:
        error_msg = AIMessage(content=f"调用模型时出错: {str(e)}")
        return {"messages": [error_msg]}


# 创建图
workflow = StateGraph(ChatState)
workflow.add_node("chatbot", chatbot_node)
workflow.set_entry_point("chatbot")
workflow.add_edge("chatbot", END)

# 编译图
graph = workflow.compile()
