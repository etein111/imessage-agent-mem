"""
记忆管理节点
负责加载和保存对话记忆，以及触发记忆整理仪式
"""
import json
from typing import Dict, Any,List
from langchain_core.messages import HumanMessage, AIMessage

from src.app.graph.state import PipelineState
from src.app.memory.redis_store import redis_store

from src.app.graph.nodes.llm_nodes import (
    check_fragment_intent_node,
    generate_fragment_node,
    consolidate_memory_node
)
from src.app.memory.mem0_store import AsyncMem0Adapter,build_mem0_adapter
_mem0_singleton = None

async def get_mem0() -> AsyncMem0Adapter:
    global _mem0_singleton
    if _mem0_singleton is None:
        _mem0_singleton = await build_mem0_adapter()
    return _mem0_singleton

import asyncio
import logging

logger = logging.getLogger(__name__)

async def _persist_overflow_to_mem0(user_id: str, overflow_msgs: list):
    try:
        mem0 = await get_mem0()

        # 给一个上限，避免后台任务无限挂着
        await asyncio.wait_for(
            mem0.add_messages(
                overflow_msgs,
                user_id=user_id,
                infer=True,
            ),
            timeout=30,  # 自己调，比如 30-120s
        )
        logger.info("mem0 persist success user_id=%s items=%d", user_id, len(overflow_msgs))

    except asyncio.TimeoutError:
        logger.warning("mem0 persist timeout user_id=%s", user_id)
    except Exception as e:
        logger.exception("mem0 persist failed user_id=%s err=%s", user_id, e)
def _to_text(x) -> str:
    if x is None:
        return ""
    if isinstance(x, list):
        return "\n".join(str(i) for i in x if i is not None).strip()
    return str(x).strip()


# ==================== 加载上下文节点 ====================

async def load_context_node(state: PipelineState) -> Dict[str, Any]:
    user_id = state.get("user_id", "default_user")

    # 1) Redis: summary
    prev_summary = await redis_store.get_summary(user_id)

    # 2) Redis: short-term raw dialogue
    raw_history = await redis_store.get_context(user_id, limit=20)
    short_term_memory = [
        HumanMessage(content=m["content"]) if m["role"] == "user" else AIMessage(content=m["content"])
        for m in raw_history
        if m.get("role") in ("user", "assistant") and m.get("content") is not None
    ]

    # 3) 最新用户输入 -> query
    messages = state.get("messages", [])
    last_user_content = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            last_user_content = m.content
            break

    if isinstance(last_user_content, list):
        parts = []
        for part in last_user_content:
            if isinstance(part, dict) and "text" in part:
                parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        query = "".join(parts).strip()
    else:
        query = str(last_user_content or "").strip()

    if not query:
        query = "conversation context"

    # 4) mem0: 长期记忆（强约束：必须返回分层 dict）
    mem0 = await get_mem0()
    layered = await mem0.search(query, user_id=user_id, limit=5)

    # 这里不做兼容：直接假设 layered 是 {"profile": [...], "episodic": [...], "working": [...]}
    if not isinstance(layered, dict) or not all(k in layered for k in ("profile", "episodic", "working")):
        raise ValueError(f"mem0.search must return layered dict, got={type(layered)} keys={getattr(layered,'keys',lambda:[])()}")

    logger.info(
        "[ContextLoad] user_id=%s | query=%s | short_term=%d | profile=%d episodic=%d working=%d",
        user_id,
        query,
        len(short_term_memory),
        len(layered.get("profile") or []),
        len(layered.get("episodic") or []),
        len(layered.get("working") or []),
    )

    return {
        "short_term_memory": short_term_memory,
        "prev_summary": prev_summary,
        "long_term_memory_layered": layered,
        "query": query,
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
    await redis_store.add_message(user_id, "user", _to_text(last_human))
    await redis_store.add_message(user_id, "assistant", _to_text(last_ai))

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

    # 不阻塞主流程：后台写 mem0
        asyncio.create_task(_persist_overflow_to_mem0(user_id, overflow_msgs))

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

