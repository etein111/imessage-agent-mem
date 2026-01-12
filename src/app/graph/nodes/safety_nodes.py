"""
安全审查节点
输入过滤和输出审核
"""
from typing import Dict, Any
from langchain_core.messages import HumanMessage, AIMessage

from src.app.graph.state import PipelineState
from src.app.graph.nodes.llm_nodes import get_model


# ==================== 输入安全检查节点 ====================
async def safety_in_node(state: PipelineState, config=None) -> Dict[str, Any]:
    """
    检查用户输入是否包含不当内容
    来源: pipeline_chat_v3.py
    """
    model = await get_model()
    
    # 获取最后一条用户消息
    messages = state.get("messages", [])
    user_message = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break
    
    if not user_message:
        return {"safety_status": "safe"}
    
    # 构建安全检查提示
    safety_prompt = f"""你是内容安全审查专家。请判断以下用户输入是否安全。

【用户输入】
{user_message}

判断标准:
- 包含暴力、色情、辱骂、歧视等内容 → unsafe
- 正常的对话内容 → safe

直接回答: safe 或 unsafe"""
    
    response = await model.ainvoke([HumanMessage(content=safety_prompt)], config={"callbacks": []})
    
    # 解析结果
    result = response.content.strip().lower()
    status = "safe" if "safe" in result else "unsafe"
    
    return {"safety_status": status}


# ==================== 输出安全审核节点 ====================
# async def safety_out_node(state: PipelineState, config=None) -> Dict[str, Any]:
#     """
#     审核AI输出，必要时重写
#     来源: pipeline_chat_v3.py
#     """
#     model = await get_model()
#
#     # 获取最后一条AI消息
#     messages = list(state.get("messages", []))
#     ai_message = None
#     ai_index = None
#
#     for i in range(len(messages) - 1, -1, -1):
#         if isinstance(messages[i], AIMessage):
#             ai_message = messages[i].content
#             ai_index = i
#             break
#
#     if not ai_message:
#         return {}
#
#     # 构建审核提示
#     review_prompt = f"""你是内容安全审核专家。请审核以下AI回复是否合适。
#
# 【AI回复】
# {ai_message}
#
# 判断标准:
# - 包含不当内容、过度建议、超出能力范围的承诺 → rewrite
# - 正常友好的回复 → safe
#
# 如果需要重写，请直接给出修改后的内容。
# 如果安全，回复: safe"""
#
#     response = await model.ainvoke([HumanMessage(content=review_prompt)], config={"callbacks": []})
#
#     result = response.content.strip()
#
#     # 如果需要重写
#     if "safe" not in result.lower():
#         # 替换AI消息
#         messages[ai_index] = AIMessage(content=result)
#         return {
#             "messages": messages,
#             "safety_status": "rewritten"
#         }
#
#     return {"safety_status": "safe"}


# ==================== 生成安全回复 ====================
async def generate_safety_response(state: PipelineState) -> Dict[str, Any]:
    """
    当检测到不安全输入时，生成安全的拒绝回复
    来源: pipeline_chat_v3.py
    """
    safety_response = "抱歉，我无法回应这类内容。我们聊点其他的吧？😊"
    
    return {"messages": [AIMessage(content=safety_response)]}

