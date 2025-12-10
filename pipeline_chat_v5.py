import asyncio
from typing import Annotated, Sequence, TypedDict, List, Optional, Literal
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
try:
    from langchain_core.pydantic_v1 import BaseModel, Field
except ImportError:
    from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END, add_messages
from simple_chat import get_model, SYSTEM_PROMPT
from memory_store import SimpleMemoryStore
from memory_chat import summarize_interaction
from pipeline_chat import load_context_node, save_memory_node
from pipeline_chat_v3 import safety_in_node, check_safety_in, safety_out_node
from pipeline_chat_v4 import estimate_state_node

# 定义 V5 管道状态
class PipelineV5State(TypedDict):
    # 核心消息流
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # 上下文信息
    user_id: str
    conversation_id: str
    
    # 记忆相关
    short_term_memory: List[str]
    
    # 安全标记
    safety_status: Optional[str]
    
    # 状态估计 (V4)
    current_emotion: Optional[str]
    dialogue_type: Optional[str]
    
    # 目标规划 (V5 新增)
    current_goal: Optional[str]       # 目标标识，如 cheer_up
    goal_instruction: Optional[str]   # 给 LLM 的具体指导

# --- 节点: Plan Goal ---
async def plan_goal_node(state: PipelineV5State):
    """目标规划节点：根据状态和记忆决定当前的对话策略"""
    print("--- Node: Plan Goal ---")
    
    emotion = state.get("current_emotion", "neutral")
    dialogue_type = state.get("dialogue_type", "small_talk")
    memories = state.get("short_term_memory", [])
    
    current_goal = "casual_chat"
    goal_instruction = "保持自然、友好的对话，展现你的个性和人设。"
    
    # 简单的规则引擎 (后续可以用 LLM 替代)
    
    # 1. 情绪响应优先
    if emotion in ["sad", "stressed", "angry", "anxious"]:
        current_goal = "cheer_up"
        goal_instruction = "提供情绪价值。重点是共情和理解，少说教。使用温柔、支持性的语气。如果用户想倾诉，就多倾听；如果用户需要安慰，给出温暖的回应。"
    
    # 2. 新用户/信息收集
    elif dialogue_type == "onboarding" or len(memories) < 3:
        current_goal = "collect_profile"
        goal_instruction = "多了解用户的兴趣爱好。在自然的对话中穿插提问，比如喜欢什么电影、音乐或运动。不要像查户口一样连续提问，要循序渐进。"
        
    # 3. 深化话题
    elif dialogue_type == "small_talk" and emotion in ["happy", "neutral", "curious"]:
        # 简单的随机策略：有时候深入聊，有时候娱乐
        current_goal = "deep_talk"
        goal_instruction = "尝试延展当前话题，提出更有深度或有趣的问题。不要只停留在表面，尝试探讨观点或感受。展现你的独特见解。"
        
    # 4. 任务处理
    elif dialogue_type == "task":
        current_goal = "light_task"
        goal_instruction = "高效、准确地帮助用户完成任务。回复要简洁明了。虽然你是傲娇云朵，但在做事时要靠谱。"
        
    # 5. 默认：保持人设 (casual_chat)
    else:
        current_goal = "casual_chat"
        goal_instruction = "保持轻松愉快的聊天氛围。展现你的‘傲娇’和‘爱猫’人设。偶尔可以开开玩笑或吐槽。"

    print(f"Goal Planned: {current_goal}")
    
    return {
        "current_goal": current_goal,
        "goal_instruction": goal_instruction
    }

# --- 节点: Generate Reply (V5) ---
async def generate_reply_node_v5(state: PipelineV5State, config=None):
    """负责生成回复 (V5 版本 - 目标驱动)"""
    print("--- Node: Generate Reply (V5) ---")
    model = await get_model()
    memories = state.get("short_term_memory", [])
    
    # 获取状态和目标
    current_emotion = state.get("current_emotion", "neutral")
    # dialogue_type = state.get("dialogue_type", "small_talk") # 不直接用，已体现在 goal 中
    current_goal = state.get("current_goal", "casual_chat")
    goal_instruction = state.get("goal_instruction", "")
    
    # 构建 System Prompt
    memory_str = "\n".join([f"- {m}" for m in memories])
    memory_context = ""
    if memory_str:
        memory_context = f"\n\n【之前的记忆】\n{memory_str}"
        
    # 注入目标指令
    goal_context = f"""
\n【当前感知】
用户情绪: {current_emotion}

【当前对话目标】
Target: {current_goal}
Instruction: {goal_instruction}

请务必遵循上述 Instruction 来生成回复，同时保持你的“云朵”人设（傲娇、爱猫）。
"""
    
    full_system_prompt = SYSTEM_PROMPT + memory_context + goal_context
    
    normalized_messages: list[BaseMessage] = []
    normalized_messages.append(SystemMessage(content=full_system_prompt))
    
    for message in state["messages"]:
        if isinstance(message, SystemMessage):
            continue
        normalized_messages.append(message)
    
    try:
        response = await model.ainvoke(normalized_messages, config=config)
        return {"messages": [response], "safety_status": "pending_check"}
    except Exception as e:
        error_msg = AIMessage(content=f"出错啦: {str(e)}")
        return {"messages": [error_msg]}

# --- 构建图 ---
workflow = StateGraph(PipelineV5State)

# 添加节点
workflow.add_node("load_context", load_context_node)
workflow.add_node("estimate_state", estimate_state_node)
workflow.add_node("plan_goal", plan_goal_node) # 新增
workflow.add_node("safety_in", safety_in_node)
workflow.add_node("generate_reply", generate_reply_node_v5) # V5
workflow.add_node("safety_out", safety_out_node)
workflow.add_node("save_memory", save_memory_node)

# 流程连接
# load -> estimate -> plan -> safety_in
workflow.set_entry_point("load_context")
workflow.add_edge("load_context", "estimate_state")
workflow.add_edge("estimate_state", "plan_goal")
workflow.add_edge("plan_goal", "safety_in")

# safety_in -> (check) -> generate / save
workflow.add_conditional_edges(
    "safety_in",
    check_safety_in,
    {
        "generate_reply": "generate_reply",
        "save_memory": "save_memory"
    }
)

workflow.add_edge("generate_reply", "safety_out")
workflow.add_edge("safety_out", "save_memory")
workflow.add_edge("save_memory", END)

# 编译
graph = workflow.compile()

