"""
测试系统指令功能

运行方式:
    python test_system_commands.py
"""

import asyncio
from langchain_core.messages import HumanMessage


async def test_system_commands():
    """测试系统指令功能"""
    
    print("🧪 测试系统指令功能")
    print("=" * 70)
    
    # 导入工作流
    from app.graph import graph
    
    # 配置
    thread_id = "test-system-commands-123"
    user_id = "test_user"
    
    # ========================================
    # 测试 1: 正常对话
    # ========================================
    print("\n📝 测试 1: 正常对话")
    print("-" * 70)
    
    config = {"configurable": {"thread_id": thread_id}}
    input_state = {
        "messages": [HumanMessage(content="你好，我是小明")],
        "user_id": user_id,
        "conversation_id": thread_id,
    }
    
    print("User: 你好，我是小明")
    
    async for event in graph.astream(input_state, config, stream_mode="updates"):
        for node_name, node_output in event.items():
            if "messages" in node_output and node_output["messages"]:
                last_msg = node_output["messages"][-1]
                if hasattr(last_msg, "content"):
                    print(f"AI ({node_name}): {last_msg.content[:100]}...")
    
    # ========================================
    # 测试 2: 清空对话指令 (/clear)
    # ========================================
    print("\n\n📝 测试 2: 清空对话指令 (/clear)")
    print("-" * 70)
    
    input_state = {
        "messages": [HumanMessage(content="/clear")],
        "user_id": user_id,
        "conversation_id": thread_id,
    }
    
    print("User: /clear")
    
    async for event in graph.astream(input_state, config, stream_mode="updates"):
        for node_name, node_output in event.items():
            if "messages" in node_output and node_output["messages"]:
                last_msg = node_output["messages"][-1]
                if hasattr(last_msg, "content"):
                    print(f"AI ({node_name}):")
                    print(f"  {last_msg.content}")
    
    # ========================================
    # 测试 3: 清空后的对话（验证确实被清空）
    # ========================================
    print("\n\n📝 测试 3: 清空后的对话")
    print("-" * 70)
    
    input_state = {
        "messages": [HumanMessage(content="我叫什么名字？")],
        "user_id": user_id,
        "conversation_id": thread_id,
    }
    
    print("User: 我叫什么名字？")
    print("期望: AI 应该不记得之前的对话（thread 已清空）")
    
    async for event in graph.astream(input_state, config, stream_mode="updates"):
        for node_name, node_output in event.items():
            if "messages" in node_output and node_output["messages"]:
                last_msg = node_output["messages"][-1]
                if hasattr(last_msg, "content") and node_name == "save_memory":
                    print(f"AI: {last_msg.content[:200]}...")
    
    # ========================================
    # 测试 4: 帮助指令 (/help)
    # ========================================
    print("\n\n📝 测试 4: 帮助指令 (/help)")
    print("-" * 70)
    
    input_state = {
        "messages": [HumanMessage(content="/help")],
        "user_id": user_id,
        "conversation_id": thread_id,
    }
    
    print("User: /help")
    
    async for event in graph.astream(input_state, config, stream_mode="updates"):
        for node_name, node_output in event.items():
            if "messages" in node_output and node_output["messages"]:
                last_msg = node_output["messages"][-1]
                if hasattr(last_msg, "content"):
                    print(f"AI ({node_name}):")
                    print(f"  {last_msg.content}")
    
    # ========================================
    # 测试 5: 中文清空指令
    # ========================================
    print("\n\n📝 测试 5: 中文清空指令")
    print("-" * 70)
    
    input_state = {
        "messages": [HumanMessage(content="清空对话")],
        "user_id": user_id,
        "conversation_id": thread_id,
    }
    
    print("User: 清空对话")
    
    async for event in graph.astream(input_state, config, stream_mode="updates"):
        for node_name, node_output in event.items():
            if "messages" in node_output and node_output["messages"]:
                last_msg = node_output["messages"][-1]
                if hasattr(last_msg, "content"):
                    print(f"AI ({node_name}): {last_msg.content[:100]}...")
    
    print("\n" + "=" * 70)
    print("✅ 所有测试完成！")
    print("=" * 70)


if __name__ == "__main__":
    # 设置环境变量（如果需要）
    import os
    import sys
    
    # 添加 src 到 Python 路径
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
    
    # 运行测试
    asyncio.run(test_system_commands())

