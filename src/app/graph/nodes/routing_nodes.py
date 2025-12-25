"""
路由节点
条件判断和流程控制
"""
from typing import Literal
from src.app.graph.state import PipelineState


# ==================== 安全检查后的路由 ====================
def check_safety_in(state: PipelineState) -> Literal["safe", "unsafe"]:
    """
    检查输入安全状态，决定后续流程
    来源: pipeline_chat_v3.py
    
    Returns:
        "safe": 继续正常流程
        "unsafe": 直接返回安全回复，跳过生成
    """
    safety_status = state.get("safety_status", "safe")
    return "unsafe" if safety_status == "unsafe" else "safe"


# ==================== 工具调用路由 ====================
def route_after_safety(state: PipelineState) -> Literal["use_tool", "normal_chat"]:
    """
    根据是否需要工具调用进行路由
    来源: pipeline_chat_v6.py
    
    Returns:
        "use_tool": 需要调用工具
        "normal_chat": 普通对话
    """
    tool_to_call = state.get("tool_to_call")
    return "use_tool" if tool_to_call else "normal_chat"


# ==================== 对话类型路由 ====================
def route_by_dialogue_type(state: PipelineState) -> str:
    """
    根据对话类型路由到不同的处理节点
    
    Returns:
        dialogue_type: small_talk, support, task等
    """
    return state.get("dialogue_type", "small_talk")


# ==================== 情绪路由 ====================
def route_by_emotion(state: PipelineState) -> str:
    """
    根据用户情绪路由
    
    Returns:
        emotion: happy, sad, stressed, neutral等
    """
    return state.get("current_emotion", "neutral")


# ==================== 目标路由 ====================
def route_by_goal(state: PipelineState) -> str:
    """
    根据对话目标路由
    
    Returns:
        goal: cheer_up, collect_profile, casual_chat等
    """
    return state.get("current_goal", "casual_chat")

