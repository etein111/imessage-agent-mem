"""
外部工具封装
天气、时间、Talk Asset等工具
来源: tools.py
"""
from datetime import datetime
from typing import Dict, Any


# ==================== 工具函数 ====================
def get_time() -> str:
    """获取当前时间"""
    now = datetime.now()
    return now.strftime("%Y年%m月%d日 %H:%M:%S")


def get_weather(city: str = "北京") -> str:
    """
    获取天气信息（模拟）
    实际使用时应接入真实天气API
    """
    # 模拟天气数据
    weather_data = {
        "北京": "多云，16℃，微风",
        "上海": "晴，18℃，东风3级",
        "深圳": "多云转小雨，25-30℃，湿度高",
        "广州": "阴，22℃，南风2级",
        "杭州": "晴，17℃，西风1级",
        "成都": "多云，15℃，无风",
        "西安": "晴，14℃，北风2级",
        "纽约": "晴，12℃，西风",
        "东京": "阴，8℃，东风",
        "伦敦": "雨，7℃，西南风",
    }
    
    return weather_data.get(city, f"{city}的天气信息暂不可用")


def get_talk_asset(category: str = "默认") -> str:
    """
    获取运营话术卡片（模拟）
    实际使用时应从数据库或CMS获取
    """
    talk_assets = {
        "鼓励": "你已经很棒了！每一步努力都算数。✨",
        "共鸣": "我能理解你的感受，这种时候确实不容易。",
        "轻松": "嘿，要不要听个冷笑话？🌝",
        "默认": "有什么想聊的吗？我在这里陪着你。",
    }
    
    return talk_assets.get(category, talk_assets["默认"])


# ==================== 工具调度器 ====================
def run_tool(tool_name: str, args: Dict[str, Any]) -> str:
    """
    统一的工具调用接口
    
    Args:
        tool_name: 工具名称 (get_time, get_weather, get_talk_asset)
        args: 工具参数
    
    Returns:
        工具执行结果
    """
    if tool_name == "get_time":
        return get_time()
    elif tool_name == "get_weather":
        city = args.get("city", "北京")
        return get_weather(city)
    elif tool_name == "get_talk_asset":
        category = args.get("category", "默认")
        return get_talk_asset(category)
    else:
        return f"未知工具: {tool_name}"


# ==================== 工具注册表 ====================
AVAILABLE_TOOLS = {
    "get_time": {
        "name": "获取当前时间",
        "description": "获取当前的日期和时间",
        "parameters": {},
    },
    "get_weather": {
        "name": "查询天气",
        "description": "查询指定城市的天气情况",
        "parameters": {
            "city": "城市名称，如：北京、上海、深圳"
        },
    },
    "get_talk_asset": {
        "name": "获取话术卡片",
        "description": "获取预设的运营话术",
        "parameters": {
            "category": "话术类别：鼓励、共鸣、轻松、默认"
        },
    },
}

