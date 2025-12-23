import asyncio
import sys
import os
from colorama import init, Fore

current_dir = os.path.dirname(os.path.abspath(__file__))

src_path = os.path.abspath(os.path.join(current_dir, "../../"))

if src_path not in sys.path:
    sys.path.insert(0, src_path)

from app.memory.redis_store import redis_store
from app.graph.nodes.memory_nodes import load_context_node, save_memory_node
from app.graph.nodes.llm_nodes import generate_reply_simple_node
from app.graph.state import PipelineState
from langchain_core.messages import HumanMessage, AIMessage

init(autoreset=True)

USER_ID = "test_user_integration"


async def mock_pipeline_step(user_input: str):
    """模拟一次完整的 Graph 执行流程"""

    state = PipelineState(
        user_id=USER_ID,
        messages=[HumanMessage(content=user_input)],
        short_term_memory=[],
        prev_summary=""
    )

    # 调用源码的 load_context_node
    context_data = await load_context_node(state)

    # 更新 State
    state["short_term_memory"] = context_data["short_term_memory"]
    state["prev_summary"] = context_data["prev_summary"]

    # 构造给 LLM 的完整历史
    full_history = []
    if state["prev_summary"]:
        # 注入摘要
        full_history.append(HumanMessage(content=f"前情提要: {state['prev_summary']}"))

    full_history.extend(state["short_term_memory"])
    full_history.append(HumanMessage(content=user_input))

    # 临时覆盖 state messages 供 LLM 使用
    state["messages"] = full_history

    print(Fore.WHITE + "AI 思考中...", end="\r")
    reply_dict = await generate_reply_simple_node(state)
    ai_reply_msg = reply_dict["messages"][0]
    print(Fore.YELLOW + f"AI: {ai_reply_msg.content}")

    # 恢复 state messages 为本轮对话 (User + AI) 以便 save_node 处理
    state["messages"] = [
        HumanMessage(content=user_input),
        ai_reply_msg
    ]

    save_result = await save_memory_node(state)

    # 如果有额外消息（比如生成的碎片），打印出来
    if "messages" in save_result:
        for m in save_result["messages"]:
            print(Fore.MAGENTA + f"[系统消息] {m.content}")

    # # --- 可视化当前 Redis 存储摘要 ---
    print(Fore.WHITE + "-" * 30)
    current_len = redis_store.client.llen(redis_store._get_chat_key(USER_ID))
    summary = redis_store.get_summary(USER_ID)

    print(Fore.WHITE + f"Redis 消息数: {current_len} (阈值40触发归档)")
    if summary:
        print(Fore.YELLOW + f"📜 当前摘要: {summary[:30]}...")
    print(Fore.WHITE + "-" * 30)


async def main():
    # 清空测试数据
    redis_store.client.delete(redis_store._get_chat_key(USER_ID))
    redis_store.client.delete(redis_store._get_summary_key(USER_ID))

    print(Fore.CYAN + "🚀 集成测试启动")
    print(Fore.CYAN + "测试点：1. 意图触发碎片  2. 20轮对话触发归档")

    while True:
        try:
            user_input = input(Fore.GREEN + "\n你: ").strip()
            if user_input == "exit": break
            if not user_input: continue

            await mock_pipeline_step(user_input)

        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    asyncio.run(main())