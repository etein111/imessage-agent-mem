"""
记忆管理节点
负责加载和保存对话记忆
"""
from typing import Dict, Any
from langchain_core.messages import HumanMessage, AIMessage

from app.graph.state import PipelineState
from app.memory.session_store import SimpleMemoryStore
from app.graph.nodes.llm_nodes import process_overflow_message_node

from app.memory.redis_store import redis_store
from app.prompts.prompt_service import prompt_service


# ==================== 加载上下文节点 ====================
async def load_context_node(state: PipelineState) -> Dict[str, Any]:
    """
    加载 Redis 中的短期记忆 + 高频用户画像
    """
    user_id = state.get("user_id", "default_user")
    conversation_id = state.get("conversation_id", "default_conversation")

    # 加载聊天记录 (Context)
    raw_history = redis_store.get_context(user_id, conversation_id)
    short_term_memory = []
    for msg in raw_history:
        if msg['role'] == 'user':
            short_term_memory.append(HumanMessage(content=msg['content']))
        else:
            short_term_memory.append(AIMessage(content=msg['content']))

    # 加载用户高频画像 (Profile)
    user_profile = redis_store.get_user_profile(user_id)
    # 比如：{'current_emotion': 'happy', 'nickname': '小王'}

    # 加载人设 Prompt
    current_persona_content = None
    try:
        from app.prompts.prompt_service import prompt_service
        active_persona = prompt_service.get_user_active_persona(user_id)
        if active_persona:
            current_persona_content = active_persona['content']
    except ImportError:
        pass

    # 4. 组装返回结果
    result = {
        "short_term_memory": short_term_memory,
        "user_profile": user_profile
    }

    if current_persona_content:
        result["current_persona"] = current_persona_content

    return result

# ==================== 保存记忆节点 ====================
async def save_memory_node(state: PipelineState, config=None) -> Dict[str, Any]:
    """
    保存记忆的核心逻辑：
    1. 存入新消息
    2. 检查是否达到阈值 (20+10条)
    3. 批量清洗溢出的 10 条 旧消息
    4. 弹出的消息存入向量库
    5. 返回最新的 State
    """
    user_id = state.get("user_id", "default_user")
    conversation_id = state.get("conversation_id", "default_conversation")

    # 获取本轮最新的 User 输入和 AI 回复
    messages = state.get("messages", [])
    if not messages:
        return {}

    # 倒序查找，找到最新的一对问答
    last_human = None
    last_ai = None

    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not last_ai:
            last_ai = msg.content
        elif isinstance(msg, HumanMessage) and not last_human:
            last_human = msg.content
        if last_human and last_ai:
            break

    if not (last_human and last_ai):
        raw_history = redis_store.get_context(user_id, conversation_id)
        current_memory_objs = []
        for msg in raw_history:
            if msg['role'] == 'user':
                current_memory_objs.append(HumanMessage(content=msg['content']))
            else:
                current_memory_objs.append(AIMessage(content=msg['content']))
        return {"short_term_memory": current_memory_objs}

    redis_store.add_message(user_id, conversation_id, "user", last_human)
    redis_store.add_message(user_id, conversation_id, "assistant", last_ai)

    # 批量检查溢出
    # 一次性拿回 10 条溢出数据，或者返回空列表
    batch_overflow = redis_store.check_and_extract_overflow(user_id, conversation_id)

    if batch_overflow:
        # 这里 len(batch_overflow) 应该是 10
        print(f" 检测到 Redis 达到阈值，批量清洗 {len(batch_overflow)} 条消息...")

        consolidated_fact = await process_overflow_message_node(batch_overflow)

        if consolidated_fact:
            print(f" [批量] 提取到有价值记忆: {consolidated_fact}")

            # TODO: 这里调用 Qdrant 接口存入长期记忆
            # 让 LLM 返回 JSON List，然后这里循环 add 到 qdrant
            # await qdrant_store.add_texts(user_id, [consolidated_fact])
        else:
            print(" [批量] 溢出消息判断为无价值/闲聊，直接丢弃。")

    # 更新 User Profile
    new_emotion = state.get("current_emotion")
    if new_emotion:
        redis_store.update_user_profile(user_id, {"current_emotion": new_emotion})

    # 返回更新后的上下文
    updated_raw_history = redis_store.get_context(user_id, conversation_id)

    updated_memory_objs = []
    for msg in updated_raw_history:
        if msg['role'] == 'user':
            updated_memory_objs.append(HumanMessage(content=msg['content']))
        else:
            updated_memory_objs.append(AIMessage(content=msg['content']))

    latest_user_profile = redis_store.get_user_profile(user_id)
    return {
        "short_term_memory": updated_memory_objs,
        "user_profile": latest_user_profile
    }


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

