"""
会话记忆存储
管理短期记忆的读写
来源: memory_store.py
"""
import json
import os
from typing import List

from app.config import MEMORY_FILE, MEMORY_MAX_ITEMS


def load_store() -> dict:
    """加载记忆存储文件"""
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_store(store: dict) -> None:
    """保存记忆存储文件"""
    # 确保目录存在
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


class SimpleMemoryStore:
    """
    简单的记忆存储类
    使用本地JSON文件存储，生产环境应使用Redis/PostgreSQL
    """
    
    @staticmethod
    def get_short_term_memory(user_id: str, conversation_id: str) -> List[str]:
        """
        获取用户的短期记忆
        
        Args:
            user_id: 用户ID
            conversation_id: 会话ID (当前实现中忽略，使用全局记忆)
        
        Returns:
            记忆摘要列表
        """
        store = load_store()
        # 使用 global_memory 实现跨会话记忆
        key = f"{user_id}:global_memory"
        return store.get(key, [])
    
    @staticmethod
    def add_memory(user_id: str, conversation_id: str, summary: str) -> None:
        """
        添加新的记忆摘要
        
        Args:
            user_id: 用户ID
            conversation_id: 会话ID (当前实现中忽略)
            summary: 记忆摘要
        """
        store = load_store()
        key = f"{user_id}:global_memory"
        
        if key not in store:
            store[key] = []
        
        # 添加新记忆
        memories = store[key]
        memories.append(summary)
        
        # 保留最近N条记忆
        if len(memories) > MEMORY_MAX_ITEMS:
            memories = memories[-MEMORY_MAX_ITEMS:]
        
        store[key] = memories
        save_store(store)
    
    @staticmethod
    def clear_memory(user_id: str) -> None:
        """清除用户的所有记忆"""
        store = load_store()
        key = f"{user_id}:global_memory"
        
        if key in store:
            del store[key]
            save_store(store)
    
    @staticmethod
    def get_all_users() -> List[str]:
        """获取所有有记忆的用户ID列表"""
        store = load_store()
        users = []
        for key in store.keys():
            if ":global_memory" in key:
                user_id = key.replace(":global_memory", "")
                users.append(user_id)
        return users

