import asyncio
from typing import Annotated, Sequence, TypedDict, List, Optional
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

# 定义 V2 管道状态
class PipelineChatState(TypedDict):
    # 核心消息流
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # 上下文信息
    user_id: str
    conversation_id: str
    
    # 记忆相关
    short_term_memory: List[str]
    
    # 临时状态 (不一定需要持久化，但方便节点间传递)
    # reply: Optional[str] # 也可以直接用 messages[-1]

# --- 节点 1: Load Context ---
async def load_context_node(state: PipelineChatState):
    """负责从 Context Store 拉取数据"""
    print("--- Node: Load Context ---")
    user_id = state.get("user_id", "default_user")
    conversation_id = state.get("conversation_id", "default_session")
    
    # 如果 state 中没有 ID（比如第一轮），尝试设置默认值
    # 注意：通常这些 ID 应该在图的输入中提供
    
    memories = SimpleMemoryStore.get_short_term_memory(user_id, conversation_id)
    
    # 返回更新的状态
    return {
        "short_term_memory": memories,
        "user_id": user_id,
        "conversation_id": conversation_id
    }

# --- 节点 2: Generate Reply ---
async def generate_reply_node(state: PipelineChatState, config=None):
    """负责生成回复"""
    print("--- Node: Generate Reply ---")
    model = await get_model()
    memories = state.get("short_term_memory", [])
    
    # 构建 System Prompt
    memory_str = "\n".join([f"- {m}" for m in memories])
    memory_context = ""
    if memory_str:
        memory_context = f"\n\n【之前的记忆】\n{memory_str}\n请基于这些记忆与用户交流，不要重复问已经知道的信息。"
    
    full_system_prompt = SYSTEM_PROMPT + memory_context
    
    # 准备消息历史
    normalized_messages: list[BaseMessage] = []
    normalized_messages.append(SystemMessage(content=full_system_prompt))
    
    for message in state["messages"]:
        if isinstance(message, SystemMessage):
            continue
        normalized_messages.append(message)
    
    try:
        # 调用 LLM
        # 注意：这里流式输出会自动被 LangGraph 捕获并推送到前端
        response = await model.ainvoke(normalized_messages, config=config)
        return {"messages": [response]}
    except Exception as e:
        error_msg = AIMessage(content=f"出错啦: {str(e)}")
        return {"messages": [error_msg]}

# --- 节点 3: Save Memory ---
async def save_memory_node(state: PipelineChatState):
    """负责生成摘要并写回 Context Store"""
    print("--- Node: Save Memory ---")
    model = await get_model()
    user_id = state["user_id"]
    conversation_id = state["conversation_id"]
    messages = state["messages"]
    
    if len(messages) < 2:
        return {}

    last_ai_message = messages[-1]
    last_human_message = messages[-2]
    
    if isinstance(last_ai_message, AIMessage) and isinstance(last_human_message, HumanMessage):
        # 生成摘要
        summary = await summarize_interaction(model, last_human_message.content, last_ai_message.content)
        
        # 保存到 Store
        SimpleMemoryStore.add_memory(user_id, conversation_id, summary)
        print(f"Saved Memory for {user_id}: {summary}")
        
        # 重新读取完整列表以更新状态（方便前端展示）
        all_memories = SimpleMemoryStore.get_short_term_memory(user_id, conversation_id)
        return {"short_term_memory": all_memories}
    
    return {}

# --- 构建图 ---
workflow = StateGraph(PipelineChatState)

workflow.add_node("load_context", load_context_node)
workflow.add_node("generate_reply", generate_reply_node)
workflow.add_node("save_memory", save_memory_node)

# 线性流程
workflow.set_entry_point("load_context")
workflow.add_edge("load_context", "generate_reply")
workflow.add_edge("generate_reply", "save_memory")
workflow.add_edge("save_memory", END)

# 编译
graph = workflow.compile()




