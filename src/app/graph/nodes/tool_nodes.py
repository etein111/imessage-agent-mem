"""
工具调用节点
处理外部工具和API调用
"""
from typing import Dict, Any

from src.app.graph.state import PipelineState
from src.app.tools.external_tools import run_tool


# ==================== 工具调用节点 ====================
async def call_tools_node(state: PipelineState, config=None) -> Dict[str, Any]:
    """
    执行工具调用
    来源: pipeline_chat_v6.py
    """
    tool_name = state.get("tool_to_call")
    
    if not tool_name:
        return {"tool_results": {}}
    
    # 获取用户消息以提取参数
    messages = state.get("messages", [])
    user_message = ""
    for msg in reversed(messages):
        if msg.type == "human":
            user_message = msg.content
            break
    
    # 调用工具
    try:
        # 根据工具名调用不同的工具
        if tool_name == "weather":
            # 尝试从用户消息中提取城市
            city = extract_city_from_message(user_message)
            result = run_tool("get_weather", {"city": city})
        elif tool_name == "time":
            result = run_tool("get_time", {})
        elif tool_name == "talk_asset":
            # 提取类别
            category = extract_category_from_message(user_message)
            result = run_tool("get_talk_asset", {"category": category})
        else:
            result = f"未知工具: {tool_name}"
        
        tool_results = {tool_name: result}
    except Exception as e:
        tool_results = {tool_name: f"工具调用失败: {str(e)}"}
    
    return {"tool_results": tool_results}


# ==================== 辅助函数 ====================
def extract_city_from_message(message: str) -> str:
    """从消息中提取城市名"""
    # 简单的城市提取逻辑
    cities = ["北京", "上海", "深圳", "广州", "杭州", "成都", "西安", "纽约", "东京", "伦敦"]
    for city in cities:
        if city in message:
            return city
    return "北京"  # 默认城市


def extract_category_from_message(message: str) -> str:
    """从消息中提取话术类别"""
    categories = {
        "鼓励": ["鼓励", "打气", "加油", "支持"],
        "共鸣": ["共鸣", "理解", "感同身受"],
        "轻松": ["轻松", "有趣", "搞笑", "幽默"],
    }
    
    message_lower = message.lower()
    for category, keywords in categories.items():
        if any(kw in message_lower for kw in keywords):
            return category
    
    return "默认"  # 默认类别

