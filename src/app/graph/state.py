"""
统一的 LangGraph 状态定义
整合了所有版本的状态字段
"""
from typing import Annotated, Sequence, TypedDict, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


# ==================== 基础聊天状态 ====================
class ChatState(TypedDict):
    """简单聊天状态 (V0/V1)"""
    messages: Annotated[Sequence[BaseMessage], add_messages]


# ==================== 带记忆的聊天状态 ====================
class ConversationState(TypedDict):
    """带记忆的对话状态 (V1)"""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_id: str
    conversation_id: str
    short_term_memory: List[str]  # 短期记忆摘要列表
    reply: str  # 当前回复


# ==================== 流水线状态 (V2-V6) ====================
class PipelineState(TypedDict):
    """完整流水线状态 - 包含所有功能"""
    # 核心消息流
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # 上下文信息
    user_id: str
    conversation_id: str

    # === 记忆相关 ===
    # 短期记忆：Redis里的近20条对话 (存的是 Message 对象，不是 str)
    short_term_memory: List[BaseMessage]

    # 长期记忆
    long_term_memory_layered: Dict[str, Any]
    long_term_relations: Any

    # # 前情提要：Redis里的摘要
    # prev_summary: Optional[str]

    # 当前人设：从文件加载的 Prompt
    current_persona: Optional[str]

    # 安全标记 (V3)
    safety_status: Optional[str]  # "safe" | "unsafe" | "rewritten"
    
    # 状态估计 (V4)
    current_emotion: Optional[str]  # happy, sad, stressed, bored, neutral
    dialogue_type: Optional[str]    # small_talk, support, task, onboarding, flirt, conflict
    
    # 目标规划 (V5)
    current_goal: Optional[str]     # cheer_up, collect_profile, deep_talk, light_task, casual_chat
    goal_instruction: Optional[str]  # 目标具体指令
    
    # 工具集成 (V6)
    tool_results: Optional[Dict[str, Any]]  # 工具执行结果
    tool_to_call: Optional[str]             # 计划调用的工具名


# ==================== 类型别名 ====================
# 为了向后兼容，提供别名
PipelineV2State = ConversationState  # V2 使用 ConversationState
PipelineV3State = PipelineState      # V3+ 使用完整状态
PipelineV4State = PipelineState
PipelineV5State = PipelineState
PipelineV6State = PipelineState


# ==================== 状态工厂函数 ====================
def create_initial_state(
        user_id: str,
        conversation_id: str,
        initial_message: Optional[str] = None
) -> PipelineState:
    """创建初始状态"""
    from langchain_core.messages import HumanMessage

    state: PipelineState = {
        "messages": [HumanMessage(content=initial_message)] if initial_message else [],
        "user_id": user_id,
        "conversation_id": conversation_id,

        # === 修改初始化部分 ===
        "short_term_memory": [],
        # "prev_summary": "",  默认为空字符串
        "user_profile": {},  # 默认为空字典
        "current_persona": None,  # 默认为 None
        # ====================

        "safety_status": None,
        "current_emotion": None,
        "dialogue_type": None,
        "current_goal": None,
        "goal_instruction": None,
        "tool_results": None,
        "tool_to_call": None,
        'long_term_memory_layered': {},
        'long_term_relations': [],
        'prev_summary': None,
    }
    return state


# ==================== 状态辅助函数 ====================
def has_unsafe_content(state: PipelineState) -> bool:
    """检查状态中是否有不安全内容"""
    return state.get("safety_status") == "unsafe"


def needs_tool_call(state: PipelineState) -> bool:
    """检查是否需要调用工具"""
    return state.get("tool_to_call") is not None


def get_last_user_message(state: PipelineState) -> Optional[str]:
    """获取最后一条用户消息"""
    for msg in reversed(state["messages"]):
        if msg.type == "human":
            return msg.content
    return None


def get_last_ai_message(state: PipelineState) -> Optional[str]:
    """获取最后一条AI消息"""
    for msg in reversed(state["messages"]):
        if msg.type == "ai":
            return msg.content
    return None

