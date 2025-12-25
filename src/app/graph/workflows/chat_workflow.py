"""
主聊天工作流
整合所有功能的完整对话图 (V6)
"""
from langgraph.graph import StateGraph, END

from src.app.graph.state import PipelineState
from src.app.graph.nodes import (
    # Memory
    load_context_node,
    save_memory_node,
    
    # LLM
    generate_reply_simple_node,
    generate_reply_with_tools_node,
    estimate_state_node,
    plan_goal_node,
    
    # Safety
    safety_in_node,
    safety_out_node,
    generate_safety_response,
    
    # Tools
    call_tools_node,
    
    # Routing
    check_safety_in,
    route_after_safety,
    
    # System
    check_system_command,
    reset_conversation_node,
    show_help_node,
    list_personas_node,
    switch_persona_node,
)


def create_chat_workflow() -> StateGraph:
    """
    创建完整的聊天工作流
    
    流程:
    START
      ↓
    load_context (加载记忆)
      ↓
    check_system_command (检测系统指令) ← 新增
      ├─ reset → reset_conversation → END
      ├─ help → show_help → END
      ├─ list_personas → list_personas → END
      ├─ switch_persona → switch_persona → END
      └─ normal → estimate_state
      ↓
    estimate_state (识别情绪&类型)
      ↓
    plan_goal (规划目标&判断工具)
      ↓
    safety_in (输入安全检查)
      ↓
    [条件路由]
      ├─ unsafe → generate_safety_response
      └─ safe → [工具路由]
                  ├─ use_tool → call_tools → generate_reply_with_tools
                  └─ normal_chat → generate_reply_simple
      ↓
    safety_out (输出审核)
      ↓
    save_memory (保存记忆)
      ↓
    END
    """
    # 创建图
    workflow = StateGraph(PipelineState)
    
    # 添加节点
    workflow.add_node("load_context", load_context_node)
    
    # 系统节点 (新增)
    workflow.add_node("reset_conversation", reset_conversation_node)
    workflow.add_node("show_help", show_help_node)
    workflow.add_node("list_personas", list_personas_node)
    workflow.add_node("switch_persona", switch_persona_node)
    
    workflow.add_node("estimate_state", estimate_state_node)
    workflow.add_node("plan_goal", plan_goal_node)
    workflow.add_node("safety_in", safety_in_node)
    workflow.add_node("generate_safety_response", generate_safety_response)
    workflow.add_node("call_tools", call_tools_node)
    workflow.add_node("generate_reply_simple", generate_reply_simple_node)
    workflow.add_node("generate_reply_with_tools", generate_reply_with_tools_node)
    workflow.add_node("safety_out", safety_out_node)
    workflow.add_node("save_memory", save_memory_node)
    
    # 设置入口点
    workflow.set_entry_point("load_context")
    
    # 添加条件边: 系统指令检测 (新增)
    workflow.add_conditional_edges(
        "load_context",
        check_system_command,
        {
            "reset": "reset_conversation",     # 重置对话
            "help": "show_help",               # 显示帮助
            "list_personas": "list_personas",  # 列出提示词
            "switch_persona": "switch_persona",# 切换提示词
            "normal": "estimate_state"         # 正常对话流程
        }
    )
    
    # 系统指令处理后直接结束 (新增)
    workflow.add_edge("reset_conversation", END)
    workflow.add_edge("show_help", END)
    workflow.add_edge("list_personas", END)
    workflow.add_edge("switch_persona", END)
    
    # 正常流程的固定边
    workflow.add_edge("estimate_state", "plan_goal")
    workflow.add_edge("plan_goal", "safety_in")
    
    # 添加条件边: 安全检查后的路由
    workflow.add_conditional_edges(
        "safety_in",
        check_safety_in,
        {
            "safe": "check_tool_route",  # 继续判断是否需要工具
            "unsafe": "generate_safety_response"  # 不安全内容
        }
    )
    
    # 添加中间路由节点（用于工具判断）
    workflow.add_node("check_tool_route", lambda state: state)  # 透传状态
    workflow.add_conditional_edges(
        "check_tool_route",
        route_after_safety,
        {
            "use_tool": "call_tools",
            "normal_chat": "generate_reply_simple"
        }
    )
    
    # 工具调用后生成回复
    workflow.add_edge("call_tools", "generate_reply_with_tools")
    
    # 所有回复生成后都进入安全审核
    workflow.add_edge("generate_reply_simple", "safety_out")
    workflow.add_edge("generate_reply_with_tools", "safety_out")
    workflow.add_edge("generate_safety_response", "save_memory")  # 安全回复直接保存
    
    # 审核后保存记忆
    workflow.add_edge("safety_out", "save_memory")
    
    # 保存后结束
    workflow.add_edge("save_memory", END)
    
    return workflow


# 编译图
graph = create_chat_workflow().compile()


# 导出
__all__ = ["graph", "create_chat_workflow"]

