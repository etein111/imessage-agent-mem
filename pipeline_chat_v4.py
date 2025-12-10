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

# 定义 V4 管道状态
class PipelineV4State(TypedDict):
    # 核心消息流
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # 上下文信息
    user_id: str
    conversation_id: str
    
    # 记忆相关
    short_term_memory: List[str]
    
    # 安全标记
    safety_status: Optional[str]
    
    # 状态估计 (V4 新增)
    current_emotion: Optional[str]  # 用户情绪
    dialogue_type: Optional[str]    # 对话类型

# 定义结构化输出模型 (Pydantic) - 用于 LLM 分类
class StateEstimation(BaseModel):
    emotion: str = Field(description="用户当前的情绪状态，如: happy, sad, stressed, bored, neutral, angry, excited")
    dialogue_type: str = Field(description="当前的对话类型，如: small_talk (闲聊), support (寻求安慰), task (任务), onboarding (初次见面), flirt (调情/玩笑), conflict (冲突)")

# --- 节点: Estimate State ---
async def estimate_state_node(state: PipelineV4State):
    """状态估计节点：分析用户情绪和对话类型"""
    print("--- Node: Estimate State ---")
    messages = state["messages"]
    if not messages:
        return {}
        
    # 获取用户最新的一条消息
    last_message = messages[-1]
    if not isinstance(last_message, HumanMessage):
        return {} # 如果不是用户消息，跳过
        
    user_input = last_message.content
    
    # 简单的 Few-Shot Prompt
    prompt = f"""请分析用户当前的情绪状态和对话类型。

示例 1:
用户: "今天工作太累了，老板一直挑刺。"
情绪: stressed
类型: support

示例 2:
用户: "你叫什么名字呀？喜欢吃什么？"
情绪: curious
类型: onboarding

示例 3:
用户: "哈哈哈，你这个笨蛋AI太逗了。"
情绪: happy
类型: flirt

当前用户输入: "{user_input}"

请输出 JSON 格式，包含 emotion 和 dialogue_type 两个字段。
情绪标签参考: happy, sad, stressed, bored, neutral, angry, excited, curious
类型标签参考: small_talk, support, task, onboarding, flirt, conflict
"""
    
    model = await get_model()
    
    try:
        # 使用 with_structured_output 强制 LLM 输出 JSON 结构
        structured_llm = model.with_structured_output(StateEstimation)
        # 禁用流式回调，因为这只是内部推理
        result = await structured_llm.ainvoke([HumanMessage(content=prompt)], config={"callbacks": []})
        
        print(f"State Estimated: Emotion={result.emotion}, Type={result.dialogue_type}")
        
        return {
            "current_emotion": result.emotion,
            "dialogue_type": result.dialogue_type
        }
    except Exception as e:
        print(f"State estimation failed: {e}")
        # 降级处理：默认值
        return {
            "current_emotion": "neutral",
            "dialogue_type": "small_talk"
        }

# --- 节点: Generate Reply (V4) ---
# 需要更新 generate_reply，让它能感知到 emotion 和 dialogue_type 并调整语气
# 这里我们先简单复用 V3，或者稍微修改 Prompt 让它知道用户的情绪
async def generate_reply_node_v4(state: PipelineV4State, config=None):
    """负责生成回复 (V4 版本 - 感知情绪)"""
    print("--- Node: Generate Reply (V4) ---")
    model = await get_model()
    memories = state.get("short_term_memory", [])
    
    # 获取状态估计结果
    current_emotion = state.get("current_emotion", "neutral")
    dialogue_type = state.get("dialogue_type", "small_talk")
    
    # 构建 System Prompt
    memory_str = "\n".join([f"- {m}" for m in memories])
    memory_context = ""
    if memory_str:
        memory_context = f"\n\n【之前的记忆】\n{memory_str}"
        
    # 注入状态感知
    state_context = f"\n\n【当前感知】\n用户情绪: {current_emotion}\n对话类型: {dialogue_type}\n请根据用户的情绪调整你的回复语气。例如：如果用户 sad/stressed，请更温柔体贴；如果用户 happy/flirt，可以更活泼傲娇。"
    
    full_system_prompt = SYSTEM_PROMPT + memory_context + state_context
    
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
workflow = StateGraph(PipelineV4State)

# 添加节点
workflow.add_node("load_context", load_context_node)
workflow.add_node("estimate_state", estimate_state_node) # 新增
workflow.add_node("safety_in", safety_in_node)
workflow.add_node("generate_reply", generate_reply_node_v4) # 更新为 V4
workflow.add_node("safety_out", safety_out_node)
workflow.add_node("save_memory", save_memory_node)

# 流程连接
# load_context -> estimate_state -> safety_in
workflow.set_entry_point("load_context")
workflow.add_edge("load_context", "estimate_state")
workflow.add_edge("estimate_state", "safety_in")

# safety_in -> (check) -> generate_reply / save_memory
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

