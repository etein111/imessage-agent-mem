import json
import time
import redis.asyncio as redis
from typing import List, Dict, Optional, Any
from app.config import get_redis_config

class RedisMemoryStore:
    def __init__(self):
        config = get_redis_config()
        self.client = redis.Redis(**config)
        # 允许缓冲到20轮(40条)，然后一次性清洗掉旧的10轮(20条)。
        self.window_size = 4
        self.trigger_limit = 8
        self.batch_size = 4

        self.ttl = 60 * 60 * 24 * 1

    def _get_chat_key(self, user_id):
        return f"chat:{user_id}"

    def _get_summary_key(self, user_id):
        return f"summary:{user_id}"

    def _get_profile_key(self, user_id):
        return f"profile:{user_id}"

    def _get_episodic_key(self, user_id):
        return f"episodic:{user_id}"

    def _get_working_key(self, user_id):
        return f"working:{user_id}"

    def _get_profile_facts_key(self, user_id):
        return f"profile_facts:{user_id}"

    async def add_message(self, user_id, role, content):
        msg = {"role": role, "content": content, "timestamp": time.time(), "time_str": time.strftime("%H:%M:%S")}
        await self.client.rpush(self._get_chat_key(user_id), json.dumps(msg, ensure_ascii=False))
        await self.client.expire(self._get_chat_key(user_id), self.ttl)

    async def get_context(self, user_id, limit=None) -> List[Dict]:
        """
        获取对话上下文。
        :param limit: 如果指定，只返回最近的 N 条（例如 load_context 时只拉取近20条）
        """
        key = self._get_chat_key(user_id)
        start = -limit if limit else 0
        raw = await self.client.lrange(key, start, -1)
        return [json.loads(m) for m in raw]

    async def get_summary(self, user_id) -> str:
        return await self.client.get(self._get_summary_key(user_id)) or ""

    async def update_summary(self, user_id, summary):
        await self.client.set(self._get_summary_key(user_id), summary)

    # --- 溢出处理 ---
    async def check_and_extract_overflow(self, user_id) -> List[Dict]:
        """
        检查是否达到触发阈值，如果达到，弹出最旧的 batch_size 条。
        """
        key = self._get_chat_key(user_id)
        current_len = await self.client.llen(key)

        if current_len >= self.trigger_limit:

            popped_raw = await self.client.lrange(key, 0, self.batch_size - 1)

            if popped_raw:
                await self.client.ltrim(key, self.batch_size, -1)

                result = []
                for msg in popped_raw:
                    if isinstance(msg, str):
                        result.append(json.loads(msg))
                    else:
                        # 处理可能返回 bytes 的情况
                        result.append(json.loads(msg.decode('utf-8')))
                return result

        return []

    async def get_profile(self, user_id) -> str:
        return await self.client.get(self._get_profile_key(user_id)) or ""

    async def update_profile(self, user_id, profile: str):
        await self.client.set(self._get_profile_key(user_id), profile)
        await self.client.expire(self._get_profile_key(user_id), self.ttl * 30)

    async def get_episodic_cache(self, user_id) -> List[str]:
        key = self._get_episodic_key(user_id)
        raw = await self.client.lrange(key, 0, -1)
        return [json.loads(m) if isinstance(m, str) else json.loads(m.decode('utf-8')) for m in raw]

    async def add_episodic_to_cache(self, user_id, episodic_memory: str):
        key = self._get_episodic_key(user_id)
        await self.client.rpush(key, json.dumps(episodic_memory, ensure_ascii=False))
        await self.client.expire(key, self.ttl)
        await self.client.ltrim(key, -20, -1)

    async def get_episodic_cache_recent(self, user_id: str, limit: int = 20) -> List[str]:
        key = self._get_episodic_key(user_id)
        raw = await self.client.lrange(key, -limit, -1)
        return [json.loads(m) if isinstance(m, str) else json.loads(m.decode('utf-8')) for m in raw]

    async def get_working_memories(self, user_id, limit: int = 20) -> List[Dict]:
        key = self._get_working_key(user_id)
        raw = await self.client.lrange(key, -limit, -1)
        return [json.loads(m) if isinstance(m, str) else json.loads(m.decode('utf-8')) for m in raw]

    async def add_working_memory(self, user_id, memory_data: Dict):
        key = self._get_working_key(user_id)
        memory_data["timestamp"] = time.time()
        await self.client.rpush(key, json.dumps(memory_data, ensure_ascii=False))
        await self.client.expire(key, self.ttl)
        await self.client.ltrim(key, -20, -1)

    async def add_profile_fact(self, user_id: str, fact: str) -> bool:
        """把一条 profile fact 加入 Redis set（自动去重）。返回是否新增。"""
        fact = (fact or "").strip()
        if not fact:
            return False
        key = self._get_profile_facts_key(user_id)
        added = await self.client.sadd(key, fact)
        await self.client.expire(key, self.ttl * 30)
        return bool(added)

    async def remove_profile_fact(self, user_id: str, fact: str) -> bool:
        """从 Redis set 删除一条 fact。返回是否真的删除了。"""
        fact = (fact or "").strip()
        if not fact:
            return False
        key = self._get_profile_facts_key(user_id)
        removed = await self.client.srem(key, fact)
        await self.client.expire(key, self.ttl * 30)
        return bool(removed)

    async def list_profile_facts(self, user_id: str, limit: Optional[int] = None) -> List[str]:
        """列出 profile facts（set 无序；如需稳定顺序可加排序策略）。"""
        key = self._get_profile_facts_key(user_id)
        raw = await self.client.smembers(key)
        facts = []
        for m in raw:
            if isinstance(m, bytes):
                facts.append(m.decode("utf-8"))
            else:
                facts.append(str(m))
        facts = [f.strip() for f in facts if f and str(f).strip()]
        # 可选：做一个稳定排序（例如字典序），保证拼接文本稳定
        facts.sort()
        if limit is not None and limit > 0:
            facts = facts[-limit:]
        return facts

    async def replace_profile_fact(self, user_id: str, old_fact: str, new_fact: str) -> bool:
        """
        用 set 近似实现 UPDATE：删 old 加 new。
        返回是否发生了变化。
        """
        old_fact = (old_fact or "").strip()
        new_fact = (new_fact or "").strip()
        if not new_fact:
            return False
        changed = False
        if old_fact and old_fact != new_fact:
            removed = await self.remove_profile_fact(user_id, old_fact)
            changed = changed or removed
        added = await self.add_profile_fact(user_id, new_fact)
        changed = changed or added
        return changed

    async def rebuild_profile_text(self, user_id: str, limit: Optional[int] = None) -> str:
        """从 facts 重建 profile 拼接文本，并写回 profile:{user_id} 这个字符串 key（兼容旧接口）。"""
        facts = await self.list_profile_facts(user_id, limit=limit)
        profile_text = "\n".join(facts)
        await self.update_profile(user_id, profile_text)
        return profile_text

# 全局实例
redis_store = RedisMemoryStore()