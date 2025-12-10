import asyncio
from typing import Annotated, Sequence, TypedDict, List, Optional, Literal, Dict, Any
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
from tools import run_tool

# 定义 V6 管道状态
class PipelineV6State(TypedDict):
    # 核心消息流
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # 上下文信息
    user_id: str
    conversation_id: str
    
    # 记忆相关
    short_term_memory: List[str]
    
    # 安全标记
    safety_status: Optional[str]
    
    # 状态估计
    current_emotion: Optional[str]
    dialogue_type: Optional[str]
    
    # 目标规划
    current_goal: Optional[str]
    goal_instruction: Optional[str]
    
    # 工具结果 (V6 新增)
    tool_results: Optional[Dict[str, Any]]
    tool_to_call: Optional[str] # 计划调用的工具名

# --- 节点: Plan Goal (V6) ---
async def plan_goal_node_v6(state: PipelineV6State):
    """目标规划节点 (V6) - 识别工具调用意图"""
    print("--- Node: Plan Goal (V6) ---")
    
    emotion = state.get("current_emotion", "neutral")
    dialogue_type = state.get("dialogue_type", "small_talk")
    memories = state.get("short_term_memory", [])
    messages = state["messages"]
    
    last_user_input = ""
    if messages and isinstance(messages[-1], HumanMessage):
        last_user_input = messages[-1].content
        
    current_goal = "casual_chat"
    goal_instruction = "保持自然、友好的对话。"
    tool_to_call = None
    
    # --- 规则引擎升级 ---
    
    # 1. 显式工具意图识别 (简单关键词)
    if "天气" in last_user_input:
        current_goal = "report_weather"
        tool_to_call = "get_weather"
        goal_instruction = "根据提供的天气信息回复用户。像云朵一样关心用户（比如提醒带伞或防晒）。"
    
    elif "时间" in last_user_input or "几点" in last_user_input:
        current_goal = "report_time"
        tool_to_call = "get_time"
        goal_instruction = "告知用户当前时间。如果很晚了，提醒早点休息。"
        
    # 2. Talk Asset 触发 (当对话类型是 small_talk 且没什么好聊的时候，或者 onboarding)
    elif dialogue_type == "onboarding" or (dialogue_type == "small_talk" and "聊什么" in last_user_input):
        current_goal = "draw_topic_card"
        tool_to_call = "get_talk_asset" # 默认取 topic_card
        goal_instruction = "使用抽取到的话题卡片开启一个新的有趣话题。"
    
    elif emotion in ["sad", "stressed"] and "安慰" in last_user_input:
        current_goal = "give_warm_quote"
        tool_to_call = "get_talk_asset" # 取 warm_quote
        goal_instruction = "送给用户一句暖心的话，并给予安慰。"

    # 3. 默认逻辑 (同 V5)
    elif emotion in ["sad", "stressed", "angry", "anxious"]:
        current_goal = "cheer_up"
        goal_instruction = "提供情绪价值。重点是共情和理解，少说教。"
    
    else:
        current_goal = "casual_chat"
        goal_instruction = "保持轻松愉快的聊天氛围。展现你的‘傲娇’和‘爱猫’人设。"

    print(f"Goal: {current_goal}, Tool: {tool_to_call}")
    
    return {
        "current_goal": current_goal,
        "goal_instruction": goal_instruction,
        "tool_to_call": tool_to_call
    }

# --- 节点: Call Tools ---
async def call_tools_node(state: PipelineV6State):
    """工具调用节点"""
    print("--- Node: Call Tools ---")
    tool_name = state.get("tool_to_call")
    current_goal = state.get("current_goal")
    
    if not tool_name:
        return {}
        
    # 准备参数
    kwargs = {}
    if current_goal == "draw_topic_card":
        kwargs["category"] = "topic_card"
    elif current_goal == "give_warm_quote":
        kwargs["category"] = "warm_quote"
    elif tool_name == "get_weather":
        # 这里可以接实体抽取模型提取城市，现在先模拟
        if "上海" in str(state["messages"][-1].content):
            kwargs["city"] = "上海"
        elif "广州" in str(state["messages"][-1].content):
            kwargs["city"] = "广州"
    
    result = run_tool(tool_name, **kwargs)
    print(f"Tool Result: {result}")
    
    return {
        "tool_results": {tool_name: result}
    }

# --- 路由: Check Tool Use ---
def check_tool_use(state: PipelineV6State) -> Literal["call_tools", "generate_reply"]:
    if state.get("tool_to_call"):
        return "call_tools"
    return "generate_reply"

# --- 节点: Generate Reply With Tools ---
async def generate_reply_with_tools_node(state: PipelineV6State, config=None):
    """使用工具结果生成回复"""
    print("--- Node: Generate Reply With Tools ---")
    model = await get_model()
    
    current_goal = state.get("current_goal")
    goal_instruction = state.get("goal_instruction")
    tool_results = state.get("tool_results", {})
    
    # 将工具结果转换为字符串
    tool_context = "\n".join([f"【工具 {k} 结果】: {v}" for k, v in tool_results.items()])
    
    # 构建 Prompt (复用 V5 的逻辑，只是加了 tool_context)
    # 这里为了简单，直接硬编码 Prompt 逻辑
    
    full_prompt = f"""{SYSTEM_PROMPT}

【当前任务】
Target: {current_goal}
Instruction: {goal_instruction}

{tool_context}

请根据工具结果和指令生成回复。
"""
    
    normalized_messages: list[BaseMessage] = []
    normalized_messages.append(SystemMessage(content=full_prompt))
    
    # 简单地把 SystemMessage 替换掉，保留用户对话历史
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

# --- 节点: Generate Reply (V5 复用) ---
# 稍微改个名方便区分，逻辑一样，就是没有 Tool Context
async def generate_reply_node_simple(state: PipelineV6State, config=None):
    print("--- Node: Generate Reply (Simple) ---")
    # 这里简单复用之前的 generate_reply_node_v5 逻辑，但需要注意 import
    # 为了代码独立性，复制 V5 逻辑并简化
    model = await get_model()
    memories = state.get("short_term_memory", [])
    current_emotion = state.get("current_emotion", "neutral")
    current_goal = state.get("current_goal", "casual_chat")
    goal_instruction = state.get("goal_instruction", "")
    
    memory_str = "\n".join([f"- {m}" for m in memories])
    memory_context = f"\n\n【之前的记忆】\n{memory_str}" if memory_str else ""
    
    goal_context = f"\n【当前感知】\n用户情绪: {current_emotion}\n【当前目标】\n{current_goal}: {goal_instruction}"
    
    full_prompt = SYSTEM_PROMPT + memory_context + goal_context
    
    normalized_messages: list[BaseMessage] = []
    for message in state["messages"]:
        if isinstance(message, SystemMessage): continue
        normalized_messages.append(message)
    normalized_messages.append(SystemMessage(content=full_prompt))

    response = await model.ainvoke(normalized_messages, config=config)
    return {"messages": [response]}


# --- 构建图 ---
workflow = StateGraph(PipelineV6State)

workflow.add_node("load_context", load_context_node)
workflow.add_node("estimate_state", estimate_state_node)
workflow.add_node("plan_goal", plan_goal_node_v6) # V6 升级版
workflow.add_node("safety_in", safety_in_node)

workflow.add_node("call_tools", call_tools_node) # V6 新增
workflow.add_node("generate_reply", generate_reply_node_simple)
workflow.add_node("generate_reply_with_tools", generate_reply_with_tools_node) # V6 新增

workflow.add_node("safety_out", safety_out_node)
workflow.add_node("save_memory", save_memory_node)

# 流程
workflow.set_entry_point("load_context")
workflow.add_edge("load_context", "estimate_state")
workflow.add_edge("estimate_state", "plan_goal")
workflow.add_edge("plan_goal", "safety_in")

# Safety In 后的分支 (unsafe -> save / safe -> check_tool -> call/reply)
def router_after_safety_in(state: PipelineV6State) -> Literal["save_memory", "call_tools", "generate_reply"]:
    # 1. 优先检查安全
    if state.get("safety_status") == "unsafe_in":
        return "save_memory"
    
    # 2. 检查工具调用
    if state.get("tool_to_call"):
        return "call_tools"
        
    # 3. 默认生成回复
    return "generate_reply"

workflow.add_conditional_edges(
    "safety_in",
    router_after_safety_in,
    {
        "save_memory": "save_memory",
        "call_tools": "call_tools",
        "generate_reply": "generate_reply"
    }
)

workflow.add_edge("call_tools", "generate_reply_with_tools")
workflow.add_edge("generate_reply_with_tools", "safety_out")
workflow.add_edge("generate_reply", "safety_out")

workflow.add_edge("safety_out", "save_memory")
workflow.add_edge("save_memory", END)

# 编译
graph = workflow.compile()

