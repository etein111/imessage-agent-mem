import asyncio
from typing import Annotated, Sequence, TypedDict, List, Optional, Literal
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langgraph.graph import StateGraph, END, add_messages
from simple_chat import get_model, SYSTEM_PROMPT
from memory_store import SimpleMemoryStore
from memory_chat import summarize_interaction
from pipeline_chat import load_context_node, save_memory_node # 复用之前的节点

# 定义 V3 管道状态
class PipelineV3State(TypedDict):
    # 核心消息流
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # 上下文信息
    user_id: str
    conversation_id: str
    
    # 记忆相关
    short_term_memory: List[str]
    
    # 安全标记
    safety_status: Optional[str] # "safe", "unsafe_in", "unsafe_out"

# --- 节点: Safety In ---
async def safety_in_node(state: PipelineV3State):
    """输入安全过滤"""
    print("--- Node: Safety In ---")
    messages = state["messages"]
    if not messages:
        return {"safety_status": "safe"}
    
    last_message = messages[-1]
    if isinstance(last_message, HumanMessage):
        content = last_message.content
        # 简单的关键词过滤
        unsafe_keywords = ["自残", "暴力", "炸弹", "杀人"]
        if any(k in content for k in unsafe_keywords):
            print(f"Unsafe input detected: {content}")
            # 直接生成拒绝回复
            refusal_msg = AIMessage(content="抱歉，作为AI云朵，我不能讨论这个话题。我们聊点别的吧？🌥️")
            return {
                "messages": [refusal_msg],
                "safety_status": "unsafe_in"
            }
    
    return {"safety_status": "safe"}

# --- 路由: Safety In Check ---
def check_safety_in(state: PipelineV3State) -> Literal["generate_reply", "save_memory"]:
    if state.get("safety_status") == "unsafe_in":
        return "save_memory" # 直接跳到保存（记录这次拒绝）
    return "generate_reply"

# --- 节点: Generate Reply (复用但需适配 V3 State) ---
# 直接复用 pipeline_chat.py 的逻辑，只需重新定义函数以匹配类型提示（虽非必须但清晰）
async def generate_reply_node_v3(state: PipelineV3State, config=None):
    """负责生成回复 (V3 版本)"""
    # 复用 pipeline_chat 的逻辑，但这里需要显式 import 或重写
    # 为了避免循环引用或类型问题，这里简单重写核心逻辑
    print("--- Node: Generate Reply (V3) ---")
    model = await get_model()
    memories = state.get("short_term_memory", [])
    
    # 构建 System Prompt
    memory_str = "\n".join([f"- {m}" for m in memories])
    memory_context = ""
    if memory_str:
        memory_context = f"\n\n【之前的记忆】\n{memory_str}\n请基于这些记忆与用户交流，不要重复问已经知道的信息。"
    
    full_system_prompt = SYSTEM_PROMPT + memory_context
    
    normalized_messages: list[BaseMessage] = []
    normalized_messages.append(SystemMessage(content=full_system_prompt))
    
    for message in state["messages"]:
        if isinstance(message, SystemMessage):
            continue
        normalized_messages.append(message)
    
    try:
        # 流式输出
        response = await model.ainvoke(normalized_messages, config=config)
        return {"messages": [response], "safety_status": "pending_check"}
    except Exception as e:
        error_msg = AIMessage(content=f"出错啦: {str(e)}")
        return {"messages": [error_msg]}

# --- 节点: Safety Out ---
async def safety_out_node(state: PipelineV3State):
    """输出安全审查"""
    print("--- Node: Safety Out ---")
    messages = state["messages"]
    last_message = messages[-1]
    
    if isinstance(last_message, AIMessage):
        content = last_message.content
        # 简单的输出检查：例如不允许包含特定敏感词，或者检查是否为空
        # 这里演示：如果回复中包含了“笨蛋”这个词（假设云朵有时候太傲娇了），我们让它礼貌一点
        if "笨蛋" in content:
            print("Unsafe output detected, rewriting...")
            model = await get_model()
            # 让 LLM 重写
            rewrite_prompt = f"请将这句话改写得更礼貌一点，保持傲娇但不要骂人：{content}"
            # 禁用 callback 防止流式输出重写过程
            rewrite_response = await model.ainvoke([HumanMessage(content=rewrite_prompt)], config={"callbacks": []})
            
            # 替换最后一条消息
            # 注意：LangGraph 的 add_messages 默认是 append。要替换需要特殊处理（如传递 ID）。
            # 但这里为了简单，我们追加一条修正消息，或者我们直接返回一个新的 messages 列表覆盖（如果 reducer 支持）。
            # LangGraph default reducer is append. 
            # 简单的 hack: 返回这一条作为新的追加，或者我们在前端只会显示最后一条。
            # 更严谨的做法是使用 Message ID 进行更新。这里我们简单地追加一条“修正版”。
            
            new_msg = AIMessage(content=rewrite_response.content)
            return {
                "messages": [new_msg], # 这会 append
                "safety_status": "rewritten"
            }
            
    return {"safety_status": "safe"}

# --- 构建图 ---
workflow = StateGraph(PipelineV3State)

workflow.add_node("load_context", load_context_node)
workflow.add_node("safety_in", safety_in_node)
workflow.add_node("generate_reply", generate_reply_node_v3)
workflow.add_node("safety_out", safety_out_node)
workflow.add_node("save_memory", save_memory_node)

# 流程连接
workflow.set_entry_point("load_context")
workflow.add_edge("load_context", "safety_in")

# 条件边：根据 Safety In 结果路由
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




