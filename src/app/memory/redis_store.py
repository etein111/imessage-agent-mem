import json
import time
import redis.asyncio as redis
from typing import List, Dict, Optional, Any

from watchfiles import awatch

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

    async def add_message(self, user_id, role, content):
        msg = {"role": role, "content": content, "timestamp": time.time(), "time_str": time.strftime("%H:%M:%S")}
        await self.client.rpush(self._get_chat_key(user_id), json.dumps(msg))
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


# 全局实例
redis_store = RedisMemoryStore()