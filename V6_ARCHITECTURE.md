# Pipeline Chat V6 - 完整架构文档

## 📊 核心脚本

### 主文件
**`pipeline_chat_v6.py`** - V6 主图定义
- 定义完整的对话流程图
- 整合所有节点和条件路由
- 导出 `graph` 供 LangGraph 运行

---

## 🧩 依赖的模块文件

### 1. **模型与人设** (`simple_chat.py`)
**导入内容**：
```python
from simple_chat import get_model, SYSTEM_PROMPT
```

**功能**：
- `get_model()` - 异步获取 Vertex AI 模型实例
- `SYSTEM_PROMPT` - 加载当前人设内容（通过 `persona_loader`）

**依赖**：
- `persona_loader.py` - 动态加载人设

---

### 2. **记忆存储** (`memory_store.py`)
**导入内容**：
```python
from memory_store import SimpleMemoryStore
```

**功能**：
- `SimpleMemoryStore.get_short_term_memory()` - 读取短期记忆
- `SimpleMemoryStore.add_memory()` - 保存新的记忆摘要

**存储方式**：
- 本地 JSON 文件：`memory_store.json`
- 格式：`{user_id}:global_memory` → 记忆列表

---

### 3. **记忆摘要生成** (`memory_chat.py`)
**导入内容**：
```python
from memory_chat import summarize_interaction
```

**功能**：
- 将用户消息和 AI 回复压缩成简短摘要
- 用于更新短期记忆

---

### 4. **基础节点** (`pipeline_chat.py`)
**导入内容**：
```python
from pipeline_chat import load_context_node, save_memory_node
```

**功能**：
- `load_context_node` - 从 Context Store 加载短期记忆
- `save_memory_node` - 保存对话摘要到 Context Store

---

### 5. **安全守护节点** (`pipeline_chat_v3.py`)
**导入内容**：
```python
from pipeline_chat_v3 import safety_in_node, check_safety_in, safety_out_node
```

**功能**：
- `safety_in_node` - 输入安全检查（不当内容、攻击性语言）
- `check_safety_in` - 路由函数，决定是否继续对话
- `safety_out_node` - 输出安全审核（审查/重写不当回复）

---

### 6. **状态估计节点** (`pipeline_chat_v4.py`)
**导入内容**：
```python
from pipeline_chat_v4 import estimate_state_node
```

**功能**：
- 识别用户情绪（happy, sad, stressed, neutral 等）
- 识别对话类型（small_talk, support, task, onboarding 等）
- 使用 few-shot LLM 分类

---

### 7. **工具集成** (`tools.py`)
**导入内容**：
```python
from tools import run_tool
```

**功能**：
- `get_time()` - 获取当前时间
- `get_weather(city)` - 获取天气信息（模拟）
- `get_talk_asset(category)` - 获取运营话术卡片（模拟）
- `run_tool(tool_name, args)` - 统一工具调用接口

---

### 8. **人设加载器** (`persona_loader.py`)
**间接依赖**（通过 `simple_chat.py`）

**功能**：
- 从 `personas/` 目录加载人设文件
- 支持环境变量 `PERSONA_NAME` 切换人设
- 默认人设：`yunduo`（云朵）

**可用人设**：
- `personas/yunduo.md` - 云朵（傲娇 AI 物种）
- `personas/youci.md` - 由此（温和拼图伙伴）

---

## 🔄 V6 工作流程图

```
START
  ↓
load_context (加载记忆)
  ↓
estimate_state (识别情绪&类型)
  ↓
plan_goal (规划目标&决定是否用工具)
  ↓
safety_in (输入安全检查)
  ↓
[条件路由]
  ├─→ call_tools (调用工具) → generate_reply_with_tools (结合工具结果生成回复)
  └─→ generate_reply_simple (普通对话)
  ↓
safety_out (输出安全审核)
  ↓
save_memory (保存记忆)
  ↓
END
```

---

## 📦 完整文件清单

### 核心逻辑文件（7个）
1. ✅ `pipeline_chat_v6.py` - V6 主图定义
2. ✅ `simple_chat.py` - 模型初始化、人设加载
3. ✅ `memory_store.py` - 记忆存储
4. ✅ `memory_chat.py` - 记忆摘要
5. ✅ `pipeline_chat.py` - 基础节点（V2）
6. ✅ `pipeline_chat_v3.py` - 安全节点（V3）
7. ✅ `pipeline_chat_v4.py` - 状态估计节点（V4）
8. ✅ `tools.py` - 工具定义

### 配置文件（2个）
1. ✅ `persona_loader.py` - 人设加载器
2. ✅ `langgraph.json` - LangGraph 注册配置

### 人设文件（2个）
1. ✅ `personas/yunduo.md` - 云朵人设
2. ✅ `personas/youci.md` - 由此人设

### 数据文件（1个）
1. ✅ `memory_store.json` - 记忆数据（运行时生成）

---

## 🎯 V6 新增功能（相比 V5）

### 1. 工具调用能力
- 天气查询
- 时间查询
- Talk Asset（运营话术卡片）

### 2. 新增节点
- `plan_goal_node_v6` - 增强的目标规划（识别工具需求）
- `call_tools_node` - 执行工具调用
- `generate_reply_with_tools_node` - 结合工具结果生成回复
- `generate_reply_simple_node` - 普通对话回复

### 3. 新增状态字段
```python
tool_results: Optional[Dict[str, Any]]  # 工具执行结果
tool_to_call: Optional[str]             # 计划调用的工具
```

### 4. 条件路由优化
- 根据 `tool_to_call` 决定调用工具还是普通对话
- 更智能的对话策略

---

## 📝 依赖关系图

```
pipeline_chat_v6.py
├── simple_chat.py
│   └── persona_loader.py
│       └── personas/*.md
├── memory_store.py
│   └── memory_store.json
├── memory_chat.py
├── pipeline_chat.py
├── pipeline_chat_v3.py
├── pipeline_chat_v4.py
└── tools.py
```

---

## 🔧 环境配置

### 环境变量
- `PERSONA_NAME` - 人设选择（默认：`yunduo`）
- `GOOGLE_CLOUD_PROJECT` - Google Cloud 项目 ID
- `GOOGLE_APPLICATION_CREDENTIALS` - GCP 认证文件路径

### Python 依赖
- `langgraph` - 图定义和执行
- `langgraph-cli` - CLI 工具
- `langchain-core` - 核心消息类型
- `langchain-google-vertexai` - Google Gemini 集成
- `google-auth` - Google 认证

---

## 🚀 启动方式

### 完整启动（推荐）
```bash
cd my_langgraph_app
./run_with_monitor.sh
```

启动以下服务：
- LangGraph 后台（端口 2024）
- Gradio 前端（端口 7860）
- 监控面板（端口 8080）

### 仅启动后台
```bash
cd my_langgraph_app
langgraph dev --host 0.0.0.0 --port 2024
```

---

## 📊 数据流

### 输入
```python
{
    "messages": [{"role": "user", "content": "..."}],
    "user_id": "user123",
    "conversation_id": "conv456"
}
```

### 输出
```python
{
    "messages": [...],  # 包含 AI 回复
    "short_term_memory": [...],  # 更新后的记忆
    "current_emotion": "happy",  # 识别的情绪
    "dialogue_type": "small_talk",  # 对话类型
    "current_goal": "casual_chat",  # 当前目标
    "tool_results": {...}  # 工具执行结果（如有）
}
```

---

## 🎨 自定义扩展

### 添加新人设
1. 在 `personas/` 创建 `.md` 文件
2. 设置 `export PERSONA_NAME=新人设名`
3. 重启服务

### 添加新工具
1. 在 `tools.py` 定义新函数
2. 在 `run_tool()` 添加路由
3. 在 `plan_goal_node_v6` 识别工具需求

### 调整记忆数量
修改 `memory_store.py` 中的记忆保留数量（当前：10条）

---

**版本**: V6  
**最后更新**: 2025-12-09  
**状态**: ✅ 生产就绪

