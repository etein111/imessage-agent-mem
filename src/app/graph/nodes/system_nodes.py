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


def check_system_command(state: PipelineState) -> Literal["reset", "help", "list_personas", "switch_persona", "normal"]:
    """
    路由函数：检测用户输入是否为系统指令
    
    支持的指令：
    - /clear, /reset, 清空对话, 重置对话 → 清除对话历史
    - /help, /? → 显示帮助信息
    - /personas, /list → 列出可用提示词
    - /persona <名称>, 切换人设 <名称> → 切换提示词
    - 其他 → 正常对话流程
    
    Returns:
        "reset": 清除对话历史
        "help": 显示帮助
        "list_personas": 列出提示词
        "switch_persona": 切换提示词
        "normal": 正常对话
    """
    # 获取最后一条用户消息
    messages = state.get("messages", [])
    if not messages:
        return "normal"

    last_message = None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_message = msg
            break

    if not last_message:
        return "normal"
    last_message = messages[-1]
    if not isinstance(last_message, HumanMessage):
        return "normal"

    content = last_message.content
    if isinstance(content, list):
        # 如果 content 是列表，拼接成字符串
        text_parts = []
        for part in content:
            if isinstance(part, dict) and "text" in part:
                text_parts.append(part["text"])
            elif isinstance(part, str):
                text_parts.append(part)
        content = "".join(text_parts)
    elif not isinstance(content, str):
        # 如果既不是 list 也不是 str，强转
        content = str(content)

    # 提取内容并标准化
    content = content.strip()
    content_lower = content.lower()
    
    # 检测清除指令
    reset_commands = [
        "/clear", "/reset", 
        "清空对话", "重置对话", "清空历史", "重置历史",
        "clear", "reset"
    ]
    if content_lower in reset_commands:
        return "reset"
    
    # 检测帮助指令
    help_commands = ["/help", "/?", "help", "帮助", "指令"]
    if content_lower in help_commands:
        return "help"
    
    # 检测列出提示词指令
    list_personas_commands = ["/personas", "/list", "提示词列表", "人设列表"]
    if content_lower in list_personas_commands:
        return "list_personas"
    
    # 检测切换提示词指令
    if content_lower.startswith("/persona ") or content_lower.startswith("切换人设 "):
        return "switch_persona"
    
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
            "**人设管理：**\n"
            "• `/personas` 或 `/list` - 查看可用提示词列表\n"
            "• `/persona <名称>` - 切换到指定提示词\n"
            "• `切换人设 <名称>` - 切换到指定提示词（中文）\n\n"
            "**帮助：**\n"
            "• `/help` 或 `/?` - 显示此帮助信息\n\n"
            "**提示：**\n"
            "- 清空对话后，我会忘记本次对话内容\n"
            "- 切换提示词会改变我的人格和回复风格\n"
            "- 直接输入消息即可正常聊天，无需任何指令\n\n"
            "有什么我可以帮你的吗？ 😊"
        )
    )
    
    return {
        "messages": [help_message]
    }


def list_personas_node(state: PipelineState) -> dict:
    """
    列出所有可用的提示词
    """
    from app.prompts.prompt_service import prompt_service
    
    try:
        personas = prompt_service.list_personas()
        
        if not personas:
            message_content = (
                "📋 **可用提示词列表**\n\n"
                "暂时没有可用的提示词。\n\n"
                "管理员可以通过提示词管理平台添加新的提示词。"
            )
        else:
            message_content = "📋 **可用提示词列表**\n\n"
            for persona in personas:
                message_content += f"• **{persona['name']}** - {persona['description'] or '无描述'}\n"
            
            message_content += (
                f"\n共 {len(personas)} 个提示词可用。\n\n"
                "使用 `/persona <名称>` 切换到指定提示词。\n"
                "例如: `/persona 云朵`"
            )
        
        list_message = AIMessage(content=message_content)
        
        return {
            "messages": [list_message]
        }
    
    except Exception as e:
        error_message = AIMessage(
            content=f"❌ 获取提示词列表失败: {str(e)}"
        )
        return {
            "messages": [error_message]
        }


def switch_persona_node(state: PipelineState) -> dict:
    """
    切换用户的提示词
    
    从用户消息中提取提示词名称，设置为用户的当前提示词
    """
    from app.prompts.prompt_service import prompt_service
    
    # 获取用户ID
    user_id = state.get("user_id", "default_user")
    
    # 获取最后一条用户消息
    messages = state.get("messages", [])
    if not messages:
        error_message = AIMessage(content="❌ 未找到用户消息")
        return {"messages": [error_message]}
    
    last_message = messages[-1]
    content = last_message.content.strip()
    
    # 提取提示词名称
    persona_name = None
    if content.lower().startswith("/persona "):
        persona_name = content[9:].strip()
    elif content.lower().startswith("切换人设 "):
        persona_name = content[5:].strip()
    
    if not persona_name:
        error_message = AIMessage(
            content=(
                "❌ 请指定提示词名称\n\n"
                "用法: `/persona <名称>` 或 `切换人设 <名称>`\n"
                "例如: `/persona 云朵`\n\n"
                "使用 `/personas` 查看可用提示词列表"
            )
        )
        return {"messages": [error_message]}
    
    try:
        # 查找提示词
        persona = prompt_service.get_persona_by_name(persona_name)
        
        if not persona:
            error_message = AIMessage(
                content=(
                    f"❌ 未找到提示词: **{persona_name}**\n\n"
                    "使用 `/personas` 查看可用提示词列表"
                )
            )
            return {"messages": [error_message]}
        
        # 设置用户提示词
        success = prompt_service.set_user_persona(user_id, persona['id'])
        
        if success:
            success_message = AIMessage(
                content=(
                    f"✅ 已切换到提示词: **{persona['name']}**\n\n"
                    f"{persona['description']}\n\n"
                    "从现在开始，我会以新的人格与你对话。\n"
                    "你可以使用 `/clear` 清空对话历史重新开始。"
                )
            )
            
            # 清空对话历史和记忆（切换人设后重新开始）
            from app.memory.session_store import SimpleMemoryStore
            try:
                SimpleMemoryStore.clear_memory(user_id)
                print(f"✅ 切换提示词后已清空用户 {user_id} 的记忆")
            except Exception as e:
                print(f"⚠️  清空记忆失败: {e}")
            
            return {
                "messages": [success_message],
                "short_term_memory": [],
                "current_emotion": "neutral",
                "dialogue_type": "onboarding",
                "current_goal": "casual_chat",
                "goal_instruction": "",
                "tool_results": {},
            }
        else:
            error_message = AIMessage(
                content=f"❌ 切换提示词失败: {persona_name}"
            )
            return {"messages": [error_message]}
    
    except Exception as e:
        error_message = AIMessage(
            content=f"❌ 切换提示词失败: {str(e)}"
        )
        return {"messages": [error_message]}


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

