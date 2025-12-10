import asyncio
import os
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

# 定义新的状态，包含用户 ID 和记忆
class ConversationState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_id: Optional[str]
    conversation_id: Optional[str]
    short_term_memory: Optional[List[str]]

async def summarize_interaction(model, user_input: str, ai_output: str) -> str:
    """将一轮对话压缩成简短的摘要"""
    summary_prompt = f"""请简要总结以下对话，提取关键信息（如用户的兴趣、提到的事实、云朵的态度等），字数控制在 50 字以内。
    
    用户: {user_input}
    云朵: {ai_output}
    
    摘要:"""
    try:
        # 显式禁用 callbacks，防止摘要生成的 token 被流式传输到前端
        response = await model.ainvoke(
            [HumanMessage(content=summary_prompt)],
            config={"callbacks": []} 
        )
        return response.content
    except:
        return f"用户聊了 {user_input[:10]}..."

async def chatbot_with_memory_node(state: ConversationState, config=None):
    """带记忆的聊天节点 - 只负责生成回复"""
    model = await get_model()
    
    # 1. 获取 ID
    user_id = state.get("user_id", "default_user")
    conversation_id = state.get("conversation_id", "default_session")
    
    if not user_id: user_id = "default_user"
    if not conversation_id: conversation_id = "default_session"

    # 2. 从 Context Store 拉取记忆
    memories = SimpleMemoryStore.get_short_term_memory(user_id, conversation_id)
    
    # 3. 构建带有记忆的 System Prompt
    memory_str = "\n".join([f"- {m}" for m in memories])
    memory_context = ""
    if memory_str:
        memory_context = f"\n\n【之前的记忆】\n{memory_str}\n请基于这些记忆与用户交流，不要重复问已经知道的信息。"
    
    full_system_prompt = SYSTEM_PROMPT + memory_context

    # 4. 准备消息历史
    normalized_messages: list[BaseMessage] = []
    normalized_messages.append(SystemMessage(content=full_system_prompt))
    
    for message in state["messages"]:
        if isinstance(message, SystemMessage):
            continue
        normalized_messages.append(message)

    # 5. 生成回复
    try:
        response = await model.ainvoke(normalized_messages, config=config)
        # 返回 messages 用于更新状态，同时透传必要的 ID 给下一个节点（虽然 state 里已有）
        return {"messages": [response]}

    except Exception as e:
        error_msg = AIMessage(content=f"出错啦: {str(e)}")
        return {"messages": [error_msg]}

async def summarize_node(state: ConversationState, config=None):
    """摘要节点 - 负责生成记忆并保存"""
    model = await get_model()
    user_id = state.get("user_id", "default_user")
    conversation_id = state.get("conversation_id", "default_session")
    
    messages = state["messages"]
    if len(messages) < 2:
        return {}

    # 获取最近的一轮对话
    last_ai_message = messages[-1]
    last_human_message = messages[-2]
    
    if isinstance(last_ai_message, AIMessage) and isinstance(last_human_message, HumanMessage):
        # 生成摘要
        summary = await summarize_interaction(model, last_human_message.content, last_ai_message.content)
        # 保存到 Store
        SimpleMemoryStore.add_memory(user_id, conversation_id, summary)
        print(f"Refreshed Memory for {user_id}: {summary}")
        
        # 重新读取完整记忆，以便前端更新显示
        all_memories = SimpleMemoryStore.get_short_term_memory(user_id, conversation_id)
        
        return {"short_term_memory": all_memories}
    
    return {}

# 创建图
workflow = StateGraph(ConversationState)
workflow.add_node("chatbot", chatbot_with_memory_node)
workflow.add_node("summarize", summarize_node)

workflow.set_entry_point("chatbot")
workflow.add_edge("chatbot", "summarize")
workflow.add_edge("summarize", END)

# 编译图
graph = workflow.compile()

