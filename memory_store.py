import json
import os
from typing import Dict, List, Any

MEMORY_FILE = "memory_store.json"

def load_store():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_store(store):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)

class SimpleMemoryStore:
    """模拟 Redis 的简单内存存储"""
    
    @staticmethod
    def get_short_term_memory(user_id: str, conversation_id: str) -> List[str]:
        """获取指定用户/会话的短期记忆摘要"""
        store = load_store()
        # 为了演示跨会话记忆，我们只使用 user_id 作为 key
        # 实际生产中可能需要区分 session，或者有 Global Memory 和 Session Memory 之分
        key = f"{user_id}:global_memory"
        return store.get(key, [])

    @staticmethod
    def add_memory(user_id: str, conversation_id: str, summary: str):
        """添加一条新的记忆摘要"""
        store = load_store()
        key = f"{user_id}:global_memory"
        if key not in store:
            store[key] = []
        
        # 简单策略：保留最近 10 条摘要
        memories = store[key]
        memories.append(summary)
        if len(memories) > 10:
            memories = memories[-10:]
        
        store[key] = memories
        save_store(store)

