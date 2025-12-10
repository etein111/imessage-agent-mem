"""
记忆管理节点
负责加载和保存对话记忆
"""
from typing import Dict, Any
from langchain_core.messages import HumanMessage, AIMessage

from app.graph.state import PipelineState
from app.memory.session_store import SimpleMemoryStore


# ==================== 加载上下文节点 ====================
async def load_context_node(state: PipelineState) -> Dict[str, Any]:
    """
    从 Context Store 加载用户的短期记忆和个性化提示词
    来源: pipeline_chat.py
    
    功能扩展：
    - 加载短期记忆
    - 加载用户当前激活的提示词（如果有）
    """
    user_id = state.get("user_id", "default_user")
    conversation_id = state.get("conversation_id", "default_conversation")
    
    # 从存储中获取记忆
    short_term_memory = SimpleMemoryStore.get_short_term_memory(user_id, conversation_id)
    
    # 加载用户的个性化提示词（新增）
    current_persona_content = None
    try:
        from app.prompts.prompt_service import prompt_service
        active_persona = prompt_service.get_user_active_persona(user_id)
        
        if active_persona:
            current_persona_content = active_persona['content']
            print(f"✅ 已为用户 {user_id} 加载提示词: {active_persona['name']}")
        else:
            print(f"ℹ️  用户 {user_id} 未设置提示词，使用默认提示词")
    except Exception as e:
        print(f"⚠️  加载提示词失败: {e}，使用默认提示词")
    
    result = {"short_term_memory": short_term_memory}
    
    # 如果有个性化提示词，添加到state
    if current_persona_content:
        result["current_persona"] = current_persona_content
    
    return result


# ==================== 保存记忆节点 ====================
async def save_memory_node(state: PipelineState, config=None) -> Dict[str, Any]:
    """
    保存对话摘要到 Context Store
    来源: pipeline_chat.py
    """
    from app.graph.nodes.llm_nodes import summarize_interaction
    
    user_id = state.get("user_id", "default_user")
    conversation_id = state.get("conversation_id", "default_conversation")
    
    # 获取最后一轮对话
    messages = state.get("messages", [])
    if len(messages) < 2:
        return {"short_term_memory": state.get("short_term_memory", [])}
    
    # 提取用户输入和AI回复
    user_input = None
    ai_output = None
    
    for msg in reversed(messages):
        if ai_output is None and isinstance(msg, AIMessage):
            ai_output = msg.content
        elif user_input is None and isinstance(msg, HumanMessage):
            user_input = msg.content
        
        if user_input and ai_output:
            break
    
    if not (user_input and ai_output):
        return {"short_term_memory": state.get("short_term_memory", [])}
    
    # 生成摘要
    from app.graph.nodes.llm_nodes import get_model
    model = await get_model()
    summary = await summarize_interaction(model, user_input, ai_output)
    
    # 保存到存储
    SimpleMemoryStore.add_memory(user_id, conversation_id, summary)
    
    # 返回更新后的记忆列表
    all_memories = SimpleMemoryStore.get_short_term_memory(user_id, conversation_id)
    
    return {"short_term_memory": all_memories}


# ==================== 记忆辅助函数 ====================
def format_memory_context(memories: list) -> str:
    """将记忆列表格式化为上下文字符串"""
    if not memories:
        return "（暂无历史记忆）"
    
    formatted = "\n".join([f"- {mem}" for mem in memories])
    return f"【历史记忆摘要】\n{formatted}"


def get_recent_memories(state: PipelineState, count: int = 5) -> list:
    """获取最近N条记忆"""
    memories = state.get("short_term_memory", [])
    return memories[-count:] if len(memories) > count else memories

