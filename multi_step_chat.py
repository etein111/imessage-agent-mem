"""多步骤 LangGraph 示例 - 展示完整的执行流程"""
import asyncio
import os
from pathlib import Path
from typing import Annotated, Sequence, TypedDict
import time

import google.auth
from google.auth import exceptions as google_auth_exceptions
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, END, add_messages


class ChatState(TypedDict):
    """聊天状态"""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    step_count: int  # 记录执行步骤数


def analyze_input_node(state: ChatState):
    """分析用户输入的节点"""
    last_message = state["messages"][-1]
    if isinstance(last_message, HumanMessage):
        # 处理 content 可能是字符串或列表的情况
        user_input = last_message.content
        if isinstance(user_input, list):
            user_input = " ".join(str(item) for item in user_input)
        elif not isinstance(user_input, str):
            user_input = str(user_input)
        
        user_input_lower = user_input.lower()
        
        # 分析输入类型
        if "计算" in user_input or "calculate" in user_input_lower or "+" in user_input or "-" in user_input:
            analysis = "需要计算"
        elif "?" in user_input or "？" in user_input:
            analysis = "需要回答问题"
        elif "你好" in user_input or "hello" in user_input_lower:
            analysis = "问候"
        else:
            analysis = "普通对话"
        
        # 添加分析结果到消息中（用于追踪）
        analysis_msg = AIMessage(
            content=f"[分析步骤] 检测到输入类型: {analysis}"
        )
        return {
            "messages": [analysis_msg],
            "step_count": state.get("step_count", 0) + 1
        }
    return {"step_count": state.get("step_count", 0) + 1}


def process_request_node(state: ChatState):
    """处理请求的节点"""
    last_user_msg = None
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            last_user_msg = msg
            break
    
    if last_user_msg:
        # 处理 content 可能是字符串或列表的情况
        user_input = last_user_msg.content
        if isinstance(user_input, list):
            user_input = " ".join(str(item) for item in user_input)
        elif not isinstance(user_input, str):
            user_input = str(user_input)
        
        # 根据分析结果处理
        if "计算" in user_input or "+" in user_input or "-" in user_input:
            # 简单的计算逻辑
            try:
                # 提取数字
                numbers = [int(s) for s in user_input.split() if s.isdigit()]
                if "+" in user_input and len(numbers) >= 2:
                    result = sum(numbers)
                    response = f"计算结果: {numbers[0]} + {numbers[1]} = {result}"
                elif "-" in user_input and len(numbers) >= 2:
                    result = numbers[0] - numbers[1]
                    response = f"计算结果: {numbers[0]} - {numbers[1]} = {result}"
                else:
                    response = f"我收到了计算请求: {user_input}"
            except:
                response = f"我收到了计算请求: {user_input}，但无法解析"
        elif "?" in user_input or "？" in user_input:
            response = f"关于你的问题 '{user_input}'，我正在思考中..."
        elif "你好" in user_input or "hello" in user_input.lower():
            response = "你好！我是 LangGraph 多步骤聊天机器人。我可以分析你的输入并给出响应！"
        else:
            response = f"我收到了你的消息: {user_input}\n\n[处理完成]"
        
        process_msg = AIMessage(content=f"[处理步骤] {response}")
        return {
            "messages": [process_msg],
            "step_count": state.get("step_count", 0) + 1
        }
    
    return {"step_count": state.get("step_count", 0) + 1}


# 在模块级别缓存模型，避免每次调用都初始化
_model_cache = None
_model_lock = asyncio.Lock()


async def get_model():
    """获取或创建模型实例（延迟初始化，在异步线程中）"""
    global _model_cache
    if _model_cache is None:
        async with _model_lock:
            if _model_cache is None:
                from langchain_google_vertexai import ChatVertexAI
                
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
                        max_output_tokens=1024,
                        streaming=True,  # 启用流式输出
                        credentials=credentials,
                        project=project,
                        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
                    )

                _model_cache = await asyncio.to_thread(_init_model)
    return _model_cache


async def generate_response_node(state: ChatState):
    """生成最终响应的节点 - 使用 Google Gemini 流式输出"""
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

    response = await model.ainvoke(normalized_messages)
    
    # 确保响应有内容
    if not response or not response.content:
        # 如果响应为空，返回一个错误消息
        from langchain_core.messages import AIMessage
        error_msg = AIMessage(content="抱歉，模型没有返回任何内容。请重试。")
        return {
            "messages": [error_msg],
            "step_count": state.get("step_count", 0) + 1
        }

    return {
        "messages": [response],
        "step_count": state.get("step_count", 0) + 1
    }


# 创建多步骤图
workflow = StateGraph(ChatState)

# 添加节点
workflow.add_node("analyze", analyze_input_node)
workflow.add_node("process", process_request_node)
workflow.add_node("generate", generate_response_node)

# 设置入口点
workflow.set_entry_point("analyze")

# 添加边：analyze -> process -> generate -> END
workflow.add_edge("analyze", "process")
workflow.add_edge("process", "generate")
workflow.add_edge("generate", END)

# 编译图
graph = workflow.compile()

