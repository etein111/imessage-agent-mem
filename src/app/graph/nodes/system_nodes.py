"""
系统节点 - 处理系统指令和特殊操作

包括：
- 清除对话历史
- 显示帮助信息
- 未来扩展：切换人设等
"""

from typing import Literal
from langchain_core.messages import AIMessage, HumanMessage
from ..state import PipelineState


def check_system_command(state: PipelineState) -> Literal["reset", "help", "normal"]:
    """
    路由函数：检测用户输入是否为系统指令
    
    支持的指令：
    - /clear, /reset, 清空对话, 重置对话 → 清除对话历史
    - /help, /? → 显示帮助信息
    - 其他 → 正常对话流程
    
    Returns:
        "reset": 清除对话历史
        "help": 显示帮助
        "normal": 正常对话
    """
    # 获取最后一条用户消息
    messages = state.get("messages", [])
    if not messages:
        return "normal"
    
    last_message = messages[-1]
    if not isinstance(last_message, HumanMessage):
        return "normal"
    
    # 提取内容并标准化
    content = last_message.content.strip().lower()
    
    # 检测清除指令
    reset_commands = [
        "/clear", "/reset", 
        "清空对话", "重置对话", "清空历史", "重置历史",
        "clear", "reset"
    ]
    if content in reset_commands:
        return "reset"
    
    # 检测帮助指令
    help_commands = ["/help", "/?", "help", "帮助", "指令"]
    if content in help_commands:
        return "help"
    
    # 默认正常对话
    return "normal"


def reset_conversation_node(state: PipelineState) -> dict:
    """
    重置对话节点
    
    功能：
    1. 清空对话历史（messages）
    2. 清空短期记忆（short_term_memory）
    3. 清空长期记忆（memory_store）← 新增
    4. 重置情绪和对话状态
    5. 返回确认消息
    
    完全清空用户的所有记忆，就像第一次见面一样
    """
    # 清空长期记忆（新增）
    user_id = state.get("user_id", "default_user")
    from app.memory.session_store import SimpleMemoryStore
    
    try:
        SimpleMemoryStore.clear_memory(user_id)
        print(f"✅ 已清空用户 {user_id} 的长期记忆")
    except Exception as e:
        print(f"⚠️  清空长期记忆失败: {e}")
    
    # 生成确认消息
    confirmation_message = AIMessage(
        content=(
            "✅ **对话历史已清空**\n\n"
            "我们重新开始吧！有什么想聊的吗？ 😊"
        )
    )
    
    # 返回重置后的状态
    # 只保留确认消息，清空其他对话内容
    return {
        "messages": [confirmation_message],
        "short_term_memory": [],  # 清空短期记忆
        "current_emotion": "neutral",  # 重置情绪
        "dialogue_type": "onboarding",  # 重置对话类型
        "current_goal": "casual_chat",  # 重置目标
        "goal_instruction": "",  # 清空目标指令
        "tool_results": {},  # 清空工具结果
    }


def show_help_node(state: PipelineState) -> dict:
    """
    显示帮助信息节点
    
    返回可用的系统指令列表
    """
    help_message = AIMessage(
        content=(
            "🤖 **系统指令帮助**\n\n"
            "以下是可用的系统指令：\n\n"
            "**对话管理：**\n"
            "• `/clear` 或 `/reset` - 清空对话历史\n"
            "• `清空对话` - 清空对话历史（中文）\n\n"
            "**帮助：**\n"
            "• `/help` 或 `/?` - 显示此帮助信息\n\n"
            "**提示：**\n"
            "- 清空对话后，我会忘记本次对话内容，但仍记得你的基本信息\n"
            "- 直接输入消息即可正常聊天，无需任何指令\n\n"
            "有什么我可以帮你的吗？ 😊"
        )
    )
    
    return {
        "messages": [help_message]
    }


# 可选：深度清除（包括长期记忆）
def deep_reset_conversation_node(state: PipelineState) -> dict:
    """
    深度重置对话节点（慎用）
    
    与 reset_conversation_node 的区别：
    - 这个函数会标记需要清除长期记忆
    - 需要在 save_memory_node 中响应这个标记
    
    使用场景：
    - 用户明确要求"完全忘记我"
    - 隐私保护需求
    """
    confirmation_message = AIMessage(
        content=(
            "✅ **所有记忆已清空**\n\n"
            "我已完全忘记关于你的所有信息。\n"
            "我们就像第一次见面一样，重新开始吧！ 😊"
        )
    )
    
    return {
        "messages": [confirmation_message],
        "short_term_memory": [],
        "current_emotion": "neutral",
        "dialogue_type": "onboarding",
        "current_goal": "casual_chat",
        "goal_instruction": "",
        "tool_results": {},
        # 添加标记，表示需要清除长期记忆
        "_clear_long_term_memory": True,  # 自定义标记
    }

