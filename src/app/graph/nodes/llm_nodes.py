"""
LLM 调用节点
所有与大模型交互的节点函数
"""
import asyncio
from typing import Dict, Any, Optional, List
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
try:
    from pydantic import BaseModel, Field
except ImportError:
    from langchain_core.pydantic_v1 import BaseModel, Field

from app.graph.state import PipelineState
from app.config import get_llm_model, get_system_prompt


# ==================== 模型获取 ====================
_model = None
_model_lock = asyncio.Lock()

async def get_model():
    """获取或创建模型实例（单例模式）"""
    global _model
    if _model is None:
        async with _model_lock:
            if _model is None:
                _model = get_llm_model()
    return _model


# ==================== 生成回复节点 ====================
async def generate_reply_simple_node(state: PipelineState, config=None) -> Dict[str, Any]:
    """
    生成普通对话回复（不使用工具）
    """
    model = await get_model()

    # System Prompt (人设)
    current_persona = state.get("current_persona")
    if current_persona:
        system_prompt = current_persona
    else:
        system_prompt = get_system_prompt()

    # 注入前情提要 (摘要)
    prev_summary = state.get("prev_summary", "")
    if prev_summary:
        system_prompt += f"\n\n【前情提要】\n{prev_summary}"

    full_messages = list(state.get("short_term_memory", []))

    incoming_messages = state.get("messages", [])
    if incoming_messages:
        last_msg = incoming_messages[-1]
        if isinstance(last_msg, HumanMessage):
            full_messages.append(last_msg)

    full_messages.insert(0, SystemMessage(content=system_prompt))

    response = await model.ainvoke(full_messages, config=config)

    return {"messages": [response]}


# ==================== 生成回复节点 ====================
async def generate_reply_with_tools_node(state: PipelineState, config=None) -> Dict[str, Any]:
    """
    结合工具结果生成回复
    """
    model = await get_model()

    current_persona = state.get("current_persona")
    if current_persona:
        system_prompt = current_persona
    else:
        system_prompt = get_system_prompt()

    tool_results = state.get("tool_results", {})
    messages = list(state.get("messages", []))

    tool_context = "\n".join([f"{k}: {v}" for k, v in tool_results.items()])
    enhanced_prompt = f"""{system_prompt}

【工具查询结果】
{tool_context}

请根据以上工具返回的信息，自然地回复用户。"""

    messages.insert(0, SystemMessage(content=enhanced_prompt))
    response = await model.ainvoke(messages, config=config)
    return {"messages": [response]}


# ==================== 状态估计节点 ====================
async def estimate_state_node(state: PipelineState, config=None) -> Dict[str, Any]:
    model = await get_model()
    short_term_memory = state.get("short_term_memory", [])
    messages = state.get("messages", [])
    current_user_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            current_user_msg = msg.content
            break

    if short_term_memory:
        # 格式化为 "human: 内容 \n ai: 内容"
        memory_context = "\n".join(
            [f"{msg.type}: {msg.content}" for msg in short_term_memory]
        )
    else:
        memory_context = "无历史记录"

    prompt = f"""你是一个情绪和对话类型分类专家。请分析用户的当前状态。

【历史记忆】
{memory_context}

【当前用户消息】
{current_user_msg}

请分析:
1. 用户情绪 (emotion): happy, sad, stressed, bored, neutral
2. 对话类型 (dialogue_type): small_talk, support, task, onboarding

输出格式:
emotion: <情绪>
dialogue_type: <类型>"""

    response = await model.ainvoke([HumanMessage(content=prompt)])
    content = response.content.lower()
    emotion = "neutral"
    dialogue_type = "small_talk"

    for line in content.split("\n"):
        if "emotion:" in line:
            emotion = line.split(":")[-1].strip()
        elif "dialogue_type:" in line:
            dialogue_type = line.split(":")[-1].strip()

    return {
        "current_emotion": emotion,
        "dialogue_type": dialogue_type
    }


# ==================== 目标规划节点 ====================
async def plan_goal_node(state: PipelineState, config=None) -> Dict[str, Any]:
    model = await get_model()
    emotion = state.get("current_emotion", "neutral")
    dialogue_type = state.get("dialogue_type", "small_talk")
    short_term_memory = state.get("short_term_memory", [])
    messages = state.get("messages", [])

    current_user_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            current_user_msg = msg.content
            break

    recent_msgs = short_term_memory[-3:] if short_term_memory else []
    if recent_msgs:
        memory_context = "\n".join(
            [f"{msg.type}: {msg.content}" for msg in recent_msgs]
        )
    else:
        memory_context = "无历史"

    prompt = f"""你是一个对话策略规划专家。
【用户情绪】{emotion}
【对话类型】{dialogue_type}
【最近记忆】{memory_context}
【当前消息】{current_user_msg}

请判断:
1. 是否需要调用工具? (weather, time, talk_asset, 或 none)
2. 对话目标是什么? (cheer_up, collect_profile, deep_talk, casual_chat, task_help等)
3. 具体指导建议

输出格式:
tool: <工具名或none>
goal: <目标>
instruction: <具体指导>"""

    response = await model.ainvoke([HumanMessage(content=prompt)])
    content = response.content.lower()
    tool_to_call = None
    current_goal = "casual_chat"
    goal_instruction = ""

    for line in content.split("\n"):
        if "tool:" in line:
            tool = line.split(":")[-1].strip()
            if tool not in ["none", "无"]:
                tool_to_call = tool
        elif "goal:" in line:
            current_goal = line.split(":")[-1].strip()
        elif "instruction:" in line:
            goal_instruction = line.split(":")[-1].strip()

    return {
        "current_goal": current_goal,
        "goal_instruction": goal_instruction,
        "tool_to_call": tool_to_call
    }


# ==================== 记忆摘要生成 ====================
async def summarize_interaction(model, user_input: str, ai_output: str) -> str:
    summary_prompt = f"""请将以下对话压缩成一条简短摘要（30字以内）：
用户: {user_input}
AI: {ai_output}
摘要:"""
    response = await model.ainvoke([HumanMessage(content=summary_prompt)])
    return response.content.strip()


# ==================== 1. 意图识别节点 (识别用户生成碎片的意图) ====================
async def check_fragment_intent_node(last_user_message: str) -> bool:
    """
    判断用户是否有生成记忆碎片的意图（显式或隐式）
    """
    model = await get_model()

    prompt = f"""
    请判断用户的这句话是否表达了想要“记录”、“留念”、“总结今天”、“保存记忆”或“结束话题并整理”的意图。

    用户输入: "{last_user_message}"

    如果是，请输出 YES。
    如果只是普通聊天，请输出 NO。
    只输出 YES 或 NO。
    """

    response = await model.ainvoke([HumanMessage(content=prompt)])
    return "YES" in response.content.strip().upper()


# ==================== 碎片生成节点 (识别用户需求) ====================
async def generate_fragment_node(recent_messages: list) -> str:
    """
    基于最近3轮对话生成记忆碎片
    """
    if not recent_messages: return ""
    model = await get_model()

    context = "\n".join([f"{m['role']}: {m['content']}" for m in recent_messages])

    prompt = f"""
    你是一个敏锐的记录员。请根据以下最近的对话片段，提炼出一个【记忆碎片】。

    【对话片段】
    {context}

    【要求】
    1. 捕捉核心事件、情绪和结局。
    2. 语言风格：简洁、深刻、像日记的一角。
    3. 格式：直接输出内容，不要标题。
    """

    response = await model.ainvoke([HumanMessage(content=prompt)])
    return response.content.strip()


# ==================== 摘要生成节点 (用于溢出归档) ====================
async def consolidate_memory_node(overflow_messages: list, prev_summary: str = "") -> str:
    """
    处理溢出的10轮对话，生成摘要
    可以通过调整prompt，方便长期记忆提取元数据等信息
    """
    if not overflow_messages: return None
    model = await get_model()

    context_text = "\n".join(
        [f"[{msg.get('time_str', '')}] {msg['role']}: {msg['content']}" for msg in overflow_messages])

    bg_info = f"【前情提要】\n{prev_summary}\n" if prev_summary else ""

    prompt = f"""请将以下对话总结为一段简练的陈述句摘要。

    {bg_info}
    【待归档对话】
    {context_text}

    要求：结合前情解决指代问题，保留关键事实和情绪变化。
    """

    response = await model.ainvoke([HumanMessage(content=prompt)])
    return response.content.strip()


