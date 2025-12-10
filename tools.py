import random
import datetime

def get_current_time() -> str:
    """获取当前时间"""
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")

def get_weather(city: str = "北京") -> str:
    """模拟获取天气信息"""
    # 这里是硬编码的模拟数据，实际可以接入 API
    weathers = ["晴朗 ☀️", "多云 ☁️", "小雨 🌧️", "大风 🌬️"]
    temps = range(15, 30)
    w = random.choice(weathers)
    t = random.choice(temps)
    return f"{city} 今天 {w}，气温 {t}℃。"

def get_talk_asset(category: str) -> str:
    """从语料库中抽取内容 (Talk Asset)"""
    assets = {
        "warm_quote": [
            "生活原本沉闷，但跑起来就有风。🏃💨",
            "你被安稳地爱着呢，要有做任何事的勇气。❤️",
            "保持热爱，奔赴山海。🌊",
            "今天也是个好天气，适合想念，也适合见面。☁️"
        ],
        "topic_card": [
            "【话题卡】如果能拥有一个超能力，你最想要什么？✨",
            "【话题卡】最近一次让你开怀大笑的事情是什么？😄",
            "【话题卡】你最喜欢的童年零食是什么？🍭",
            "【话题卡】如果可以穿越回十年前，你想对自己说什么？🕰️"
        ],
        "joke": [
            "为什么企鹅只有肚子是白的？因为手短洗不到背啊！🐧",
            "有一天0跟8在街上看见，0不屑的看了8一眼，说：胖就胖呗，还扎腰带。",
            "我不整理房间，我是乱室佳人。"
        ]
    }
    
    options = assets.get(category, assets["warm_quote"])
    return random.choice(options)

def run_tool(tool_name: str, **kwargs) -> str:
    """统一工具调用入口"""
    if tool_name == "get_time":
        return get_current_time()
    elif tool_name == "get_weather":
        city = kwargs.get("city", "北京") # 简单提取
        return get_weather(city)
    elif tool_name == "get_talk_asset":
        category = kwargs.get("category", "warm_quote")
        return get_talk_asset(category)
    else:
        return f"未知工具: {tool_name}"




