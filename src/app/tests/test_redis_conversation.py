import asyncio
import json
import os
import time
import redis
from typing import List, Dict, Any
from dotenv import load_dotenv
from openai import AsyncOpenAI
from colorama import init, Fore, Style

init(autoreset=True)

load_dotenv()

API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")

client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)


# ==================== RedisMemoryStore (自定义阈值) ====================
class TestRedisMemoryStore:
    def __init__(self, user_id, conversation_id, window_size=5, batch_size=2):
        self.client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.window_size = window_size  # 软阈值：5
        self.batch_size = batch_size  # 批量清洗：2
        self.hard_limit = window_size + batch_size  # 硬阈值：7
        self.key = f"test_chat:{user_id}:{conversation_id}"

        # 每次启动测试清空旧数据
        self.client.delete(self.key)

    def add_message(self, role: str, content: str):
        message = {
            "role": role,
            "content": content,
            "timestamp": time.time(),
            "time_str": time.strftime("%H:%M:%S")
        }
        self.client.rpush(self.key, json.dumps(message))

    def check_and_extract_overflow(self) -> List[Dict]:
        """检查是否达到硬阈值(7)，如果达到，弹出2条"""
        current_len = self.client.llen(self.key)

        if current_len >= self.hard_limit:
            print(Fore.YELLOW + f"\n[系统] ⚠️ 达到硬阈值 ({current_len}/{self.hard_limit})，触发溢出清洗...")
            # 弹出最旧的 batch_size 条
            popped_raw = self.client.lpop(self.key, self.batch_size)
            if popped_raw:
                if isinstance(popped_raw, str): popped_raw = [popped_raw]
                return [json.loads(msg) for msg in popped_raw]
        return []

    def get_context(self) -> List[Dict]:
        raw_msgs = self.client.lrange(self.key, 0, -1)
        return [json.loads(msg) for msg in raw_msgs]


# ==================== 模拟 LLM 节点功能 ====================

async def generate_ai_reply(history: List[Dict], user_input: str) -> str:
    """模拟真实的 AI 回复"""
    messages = [{"role": "system", "content": "你是一个温柔的AI伴侣，叫云朵。请简短回复（30字以内）。"}]
    for msg in history:
        messages.append({"role": msg['role'], "content": msg['content']})
    messages.append({"role": "user", "content": user_input})

    try:
        response = await client.chat.completions.create(
            model="DeepSeek-V3",
            messages=messages,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI回复出错: {e}"


async def consolidate_memory_node(overflow_messages: list) -> str:
    """模拟记忆清洗节点"""
    if not overflow_messages: return None

    context_text = ""
    for msg in overflow_messages:
        role = "User" if msg['role'] == 'user' else "AI"
        context_text += f"[{msg['time_str']}] {role}: {msg['content']}\n"

    prompt = f"""请分析以下即将被遗忘的对话片段，提取有价值的事实、实体或情绪。
如果全是闲聊（如"你好"、"在吗"），返回 "NO_INFO"。
如果有价值，请重写为一句陈述句。

片段：
{context_text}

摘要："""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"摘要生成出错: {e}"


# ==================== 主测试流程 ====================
async def main():
    user_id = "test_user"
    conv_id = "test_session"

    # 初始化：窗口5，溢出2 (即达到7条时，切掉前2条)
    store = TestRedisMemoryStore(user_id, conv_id, window_size=5, batch_size=2)

    print(Fore.CYAN + "=" * 60)
    print(
        Fore.CYAN + f"🚀 内存管理测试启动 | Window: {store.window_size} | Batch: {store.batch_size} | Trigger: {store.hard_limit}")
    print(Fore.CYAN + "=" * 60)

    while True:
        # 1. 获取用户输入
        try:
            user_input = input(Fore.GREEN + "\n你 (User): ").strip()
        except EOFError:
            break
        if not user_input or user_input.lower() in ['exit', 'quit']: break

        # 获取当前上下文用于生成回复
        current_history = store.get_context()

        # 2. 生成 AI 回复
        print(Fore.WHITE + "AI (思考中)...", end="\r")
        ai_reply = await generate_ai_reply(current_history, user_input)
        print(Fore.BLUE + f"云朵 (AI) : {ai_reply}")

        # 3. 存入 Redis (User + AI)
        store.add_message("user", user_input)
        store.add_message("assistant", ai_reply)

        # 4. 检查溢出
        overflow_msgs = store.check_and_extract_overflow()

        # ========== 可视化状态面板 ==========
        print(Fore.WHITE + "-" * 30)

        # A. 显示溢出处理结果
        if overflow_msgs:
            print(Fore.RED + f"🔥 [溢出发生] {len(overflow_msgs)} 条消息被挤出窗口:")
            for msg in overflow_msgs:
                print(Fore.RED + f"   - [{msg['role']}]: {msg['content']}")

            print(Fore.YELLOW + "正在生成摘要...")
            summary = await consolidate_memory_node(overflow_msgs)

            if summary and "NO_INFO" not in summary:
                print(Fore.MAGENTA + f"[生成摘要]: {summary}")
                print(Fore.MAGENTA + f"(模拟) 已存入向量数据库 Qdrant")
            else:
                print(Fore.CYAN + "[判断结果]: 无价值闲聊，丢弃。")
        else:
            print(Fore.GREEN + "✅ [状态]: 窗口未满，暂无溢出。")

        # B. 显示当前 Redis 缓冲区
        buffer = store.get_context()
        print(Fore.WHITE + f"[当前缓冲区] ({len(buffer)}/{store.hard_limit})")
        for idx, msg in enumerate(buffer):
            # 简单截断长文本以便显示
            content = (msg['content'][:20] + '..') if len(msg['content']) > 20 else msg['content']
            print(Fore.WHITE + f"   {idx + 1}. [{msg['role']}]: {content}")
        print(Fore.WHITE + "-" * 30)


if __name__ == "__main__":
    asyncio.run(main())