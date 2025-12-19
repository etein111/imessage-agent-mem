import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.memory.redis_store import RedisMemoryStore


def test_redis_overflow_logic():
    print("🧪 开始测试 Redis 滑动窗口与批量溢出逻辑...")

    # 1. 初始化并清空测试数据
    store = RedisMemoryStore()
    user_id = "test_user_001"
    conv_id = "test_conv_001"

    # 清理旧数据
    store.client.delete(store._get_chat_key(user_id, conv_id))

    # 2. 填充前 29 条数据 (阈值是 30，所以 29 条时不应该触发)
    print("Step 1: 填充 29 条消息...")
    for i in range(1, 30):
        store.add_message(user_id, conv_id, "user", f"消息_{i}")

    # 检查当前长度
    key = store._get_chat_key(user_id, conv_id)
    current_len = store.client.llen(key)
    print(f"   -> 当前 Redis 长度: {current_len} (预期: 29)")
    assert current_len == 29

    # 检查溢出 (预期：空)
    overflow = store.check_and_extract_overflow(user_id, conv_id)
    print(f"   -> 29条时检查溢出: {len(overflow)} 条 (预期: 0)")
    assert len(overflow) == 0

    # 3. 添加第 30 条消息 (触发点)
    print("Step 2: 添加第 30 条消息...")
    store.add_message(user_id, conv_id, "assistant", "消息_30")

    # 再次检查溢出 (预期：弹出 10 条)
    overflow = store.check_and_extract_overflow(user_id, conv_id)
    print(f"   -> 30条时检查溢出: {len(overflow)} 条 (预期: 10)")
    assert len(overflow) == 10

    # 4. 验证溢出的内容
    first_msg = overflow[0]['content']
    last_msg = overflow[-1]['content']
    print(f"   -> 溢出数据范围: {first_msg} ... {last_msg}")
    assert first_msg == "消息_1"
    assert last_msg == "消息_10"

    # 5. 验证 Redis 剩余内容 (预期：剩下 20 条，从 消息_11 到 消息_30)
    remaining = store.get_context(user_id, conv_id)
    print(f"   -> Redis 剩余长度: {len(remaining)} (预期: 20)")
    print(f"   -> 剩余数据开头: {remaining[0]['content']} (预期: 消息_11)")

    assert len(remaining) == 20
    assert remaining[0]['content'] == "消息_11"

    print("✅ Redis 逻辑测试通过！")


if __name__ == "__main__":
    test_redis_overflow_logic()