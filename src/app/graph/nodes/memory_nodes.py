"""
记忆管理节点
负责加载和保存对话记忆，以及触发记忆整理仪式
"""
from typing import Dict, Any
from langchain_core.messages import HumanMessage, AIMessage

from app.graph.state import PipelineState
from app.memory.redis_store import redis_store

from app.graph.nodes.llm_nodes import (
    check_fragment_intent_node,
    generate_fragment_node,
    consolidate_memory_node
)


# ==================== 加载上下文节点 ====================
async def load_context_node(state: PipelineState) -> Dict[str, Any]:
    user_id = state.get("user_id", "default_user")

    # 1. 加载摘要 (上十轮的总结)
    prev_summary = await redis_store.get_summary(user_id)

    # 2. 加载对话 (拉取 Redis 里最近的 20 条 / 10轮)
    raw_history = await redis_store.get_context(user_id, limit=20)

    short_term_memory = [
        HumanMessage(content=m['content']) if m['role'] == 'user' else AIMessage(content=m['content'])
        for m in raw_history
    ]

    return {
        "short_term_memory": short_term_memory,
        "prev_summary": prev_summary
    }


# ==================== 保存记忆节点 ====================
async def save_memory_node(state: PipelineState, config=None) -> Dict[str, Any]:
    user_id = state.get("user_id", "default_user")
    messages = state.get("messages", [])

    # 提取最新对话
    last_human = next((m.content for m in reversed(messages) if isinstance(m, HumanMessage)), None)
    last_ai = next((m.content for m in reversed(messages) if isinstance(m, AIMessage)), None)

    if not (last_human and last_ai): return {}

    # 1. 存入 Redis
    await redis_store.add_message(user_id, "user", last_human)
    await redis_store.add_message(user_id, "assistant", last_ai)

    extra_messages = []

    # ==================== A. 意图检测与碎片生成 ====================
    # 检测用户是否想生成碎片
    is_intent = await check_fragment_intent_node(last_human)

    if is_intent:
        print(f" 检测到用户生成碎片的意图...")
        # 拉取近 3 轮 (6条)
        recent_3_rounds = await redis_store.get_context(user_id, limit=6)
        # 生成碎片
        fragment = await generate_fragment_node(recent_3_rounds)

        if fragment:
            msg = f"已为你生成记忆碎片：\n「{fragment}」"
            extra_messages.append(AIMessage(content=msg))

    # ==================== B. 溢出检查与摘要生成 ====================
    # 检查是否达到 40 条 (20轮)
    overflow_msgs = await redis_store.check_and_extract_overflow(user_id)

    if overflow_msgs:
        print(f"达到 20 轮对话，归档旧的 10 轮...")
        # 获取旧摘要
        old_summary = await redis_store.get_summary(user_id)
        # 生成新摘要 (旧摘要 + 溢出的10轮 -> 新摘要)
        new_summary = await consolidate_memory_node(overflow_msgs, old_summary)

        if new_summary:
            await redis_store.update_summary(user_id, new_summary)
            print(f"摘要已更新: {new_summary[:20]}...")

    # 返回更新后的状态
    return {"messages": extra_messages} if extra_messages else {}

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

