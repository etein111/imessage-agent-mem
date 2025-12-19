"""
LLM 调用节点
所有与大模型交互的节点函数
"""
import asyncio
from typing import Dict, Any, Optional
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


# ==================== 生成回复节点 (简单版) ====================
async def generate_reply_simple_node(state: PipelineState, config=None) -> Dict[str, Any]:
    """
    生成普通对话回复（不使用工具）
    来源: pipeline_chat_v6.py
    
    功能扩展：
    - 支持使用用户个性化提示词（如果有current_persona）
    - 否则使用默认系统提示词
    """
    model = await get_model()
    
    # 检查是否有个性化提示词（新增）
    current_persona = state.get("current_persona")
    if current_persona:
        system_prompt = current_persona
        print("✅ 使用个性化提示词")
    else:
        system_prompt = get_system_prompt()
        print("ℹ️  使用默认提示词")
    
    # 准备消息
    messages = list(state.get("messages", []))
    
    # 添加系统提示词
    if not messages or not isinstance(messages[0], SystemMessage):
        # 添加目标指令（如果有）
        goal_instruction = state.get("goal_instruction", "")
        full_prompt = f"{system_prompt}\n\n{goal_instruction}" if goal_instruction else system_prompt
        messages.insert(0, SystemMessage(content=full_prompt))
    
    # 调用模型
    response = await model.ainvoke(messages, config=config)
    
    return {"messages": [response]}


# ==================== 生成回复节点 (带工具结果) ====================
async def generate_reply_with_tools_node(state: PipelineState, config=None) -> Dict[str, Any]:
    """
    结合工具结果生成回复
    来源: pipeline_chat_v6.py
    
    功能扩展：
    - 支持使用用户个性化提示词（如果有current_persona）
    """
    model = await get_model()
    
    # 检查是否有个性化提示词（新增）
    current_persona = state.get("current_persona")
    if current_persona:
        system_prompt = current_persona
    else:
        system_prompt = get_system_prompt()
    
    tool_results = state.get("tool_results", {})
    
    # 准备消息
    messages = list(state.get("messages", []))
    
    # 构建包含工具结果的提示
    tool_context = "\n".join([f"{k}: {v}" for k, v in tool_results.items()])
    enhanced_prompt = f"""{system_prompt}

【工具查询结果】
{tool_context}

请根据以上工具返回的信息，自然地回复用户。"""
    
    messages.insert(0, SystemMessage(content=enhanced_prompt))
    
    # 调用模型
    response = await model.ainvoke(messages, config=config)
    
    return {"messages": [response]}


# ==================== 状态估计节点 ====================
class EmotionClassification(BaseModel):
    """情绪分类结果"""
    emotion: str = Field(description="用户情绪: happy, sad, stressed, bored, neutral等")
    dialogue_type: str = Field(description="对话类型: small_talk, support, task, onboarding等")

async def estimate_state_node(state: PipelineState, config=None) -> Dict[str, Any]:
    """
    估计用户情绪和对话类型
    来源: pipeline_chat_v4.py
    """
    model = await get_model()
    
    # 获取上下文
    short_term_memory = state.get("short_term_memory", [])
    messages = state.get("messages", [])
    current_user_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            current_user_msg = msg.content
            break
    
    # 构建分类提示
    memory_context = "\n".join(short_term_memory) if short_term_memory else "无历史记录"
    
    prompt = f"""你是一个情绪和对话类型分类专家。请分析用户的当前状态。

【历史记忆】
{memory_context}

【当前用户消息】
{current_user_msg}

请分析:
1. 用户情绪 (emotion): happy（开心）, sad（悲伤）, stressed（压力大）, bored（无聊）, neutral（中性）
2. 对话类型 (dialogue_type): small_talk（闲聊）, support（需要支持）, task（任务型）, onboarding（初次见面）, flirt（调情）, conflict（冲突）

输出格式:
emotion: <情绪>
dialogue_type: <类型>"""
    
    response = await model.ainvoke([HumanMessage(content=prompt)], config={"callbacks": []})
    
    # 解析输出
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
    """
    规划对话目标和策略
    来源: pipeline_chat_v5.py / pipeline_chat_v6.py
    """
    model = await get_model()
    
    # 获取上下文
    emotion = state.get("current_emotion", "neutral")
    dialogue_type = state.get("dialogue_type", "small_talk")
    short_term_memory = state.get("short_term_memory", [])
    messages = state.get("messages", [])
    
    current_user_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            current_user_msg = msg.content
            break
    
    memory_context = "\n".join(short_term_memory[-3:]) if short_term_memory else "无历史"
    
    prompt = f"""你是一个对话策略规划专家。根据用户状态规划对话目标。

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
    
    response = await model.ainvoke([HumanMessage(content=prompt)], config={"callbacks": []})
    
    # 解析输出
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
    """
    将用户消息和AI回复压缩成摘要
    来源: memory_chat.py
    """
    summary_prompt = f"""请将以下对话压缩成一条简短摘要（30字以内）：

用户: {user_input}
AI: {ai_output}

摘要:"""
    
    response = await model.ainvoke([HumanMessage(content=summary_prompt)], config={"callbacks": []})
    return response.content.strip()


async def process_overflow_message_node(overflow_messages: list) -> str:
    """
    处理溢出的短期记忆：筛选有价值信息，生成陈述性摘要
    """
    if not overflow_messages:
        return None

    model = await get_model()

    # 格式化输入
    context_text = ""
    for msg in overflow_messages:
        role = "User" if msg['role'] == 'user' else "AI"
        time_str = msg.get('time_str', '')
        context_text += f"[{time_str}] {role}: {msg['content']}\n"

    prompt = f"""你是一个记忆整理专家。以下是用户对话中即将被归档的片段。
    用户的输入通常是碎片化的日记或小记。

    【待处理片段】
    {context_text}

    【任务】
    1. 忽略无意义的闲聊（如"哈哈"、"好的"、"晚安"），除非它们包含强烈情绪。
    2. 提取有价值的实体关系（人名、地点、事件）和用户状态（情绪、观点）。
    3. 将提取的内容重写为独立、完整的陈述句（Subject-Predicate-Object）。
    4. 如果没有有价值信息，请直接输出 "NO_INFO"。

    【示例】
    输入：
    [08:00] User: 烦死了
    [08:01] User: 又是那个经理
    [08:02] User: 非要红色的Logo
    输出：
    用户对经理感到愤怒，因为经理坚持要求红色的Logo。

    请输出摘要："""

    response = await model.ainvoke([HumanMessage(content=prompt)])
    content = response.content.strip()

    if content == "NO_INFO":
        return None

    return content