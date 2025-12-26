# LangGraph AI 社交应用 - 重构版本

## 📁 项目结构

```
my-langgraph-app/
├── src/
│   └── app/
│       ├── config.py                    # 配置管理
│       ├── graph/                       # LangGraph 图定义
│       │   ├── state.py                 # 统一状态定义
│       │   ├── nodes/                   # 所有节点函数
│       │   │   ├── llm_nodes.py        # LLM 调用节点
│       │   │   ├── memory_nodes.py     # 记忆管理节点
│       │   │   ├── safety_nodes.py     # 安全审查节点
│       │   │   ├── tool_nodes.py       # 工具调用节点
│       │   │   └── routing_nodes.py    # 路由决策节点
│       │   └── workflows/               # 工作流定义
│       │       └── chat_workflow.py    # 主聊天流程 (V6)
│       ├── tools/                       # 外部工具封装
│       │   └── external_tools.py       # 天气/时间/TalkAsset
│       ├── memory/                      # 记忆存储
│       │   ├── session_store.py        # 会话记忆存储
│       │   └── persona_loader.py       # 人设加载器
│       └── prompts/                     # 提示词模板
│           └── personas/                # 人设配置
│               ├── yunduo.md           # 云朵人设
│               └── youci.md            # 由此人设
├── langgraph_new.json                   # LangGraph 配置 (新)
├── langgraph.json                       # LangGraph 配置 (旧-兼容)
├── memory_store.json                    # 记忆数据库
└── [旧版本文件]                         # 保留向后兼容
    ├── simple_chat.py                   # V0
    ├── memory_chat.py                   # V1
    ├── pipeline_chat.py                 # V2
    ├── pipeline_chat_v3.py              # V3
    ├── pipeline_chat_v4.py              # V4
    ├── pipeline_chat_v5.py              # V5
    └── pipeline_chat_v6.py              # V6 (旧版)
```

---

## 🎯 重构目标

### 1. **模块化设计**
- 将分散在各版本的功能提取到专用模块
- 清晰的职责划分：节点、工具、记忆、配置

### 2. **可维护性**
- 统一的状态定义 (`state.py`)
- 标准化的节点函数签名
- 集中的配置管理

### 3. **可扩展性**
- 新增节点：在 `nodes/` 添加文件
- 新增工具：在 `tools/` 添加函数
- 新增人设：在 `prompts/personas/` 添加 Markdown

### 4. **向后兼容**
- 保留所有旧版本文件
- 新旧配置并存（`langgraph_new.json` vs `langgraph.json`）

---

## 🚀 快速开始

### 使用重构版本

```bash
# 1. 更新 LangGraph 配置（可选，测试用）
cp langgraph_new.json langgraph.json

# 2. 启动服务
./run_with_monitor.sh

# 3. 访问 API
# 使用 graph ID: chat_v6_refactored
```

### 切换人设

```bash
export PERSONA_NAME=youci    # 使用"由此"人设
export PERSONA_NAME=yunduo   # 使用"云朵"人设（默认）
```

---

## 📦 核心模块说明

### 1. **状态管理** (`graph/state.py`)

定义了所有版本的状态：
- `ChatState` - 简单聊天 (V0)
- `ConversationState` - 带记忆 (V1)
- `PipelineState` - 完整功能 (V2-V6)

```python
from app.graph import PipelineState, create_initial_state

# 创建初始状态
state = create_initial_state(
    user_id="user123",
    conversation_id="conv456",
    initial_message="你好"
)
```

### 2. **节点函数** (`graph/nodes/`)

| 模块 | 功能 | 来源 |
|------|------|------|
| `llm_nodes.py` | LLM 调用、状态估计、目标规划 | V4-V6 |
| `memory_nodes.py` | 加载/保存记忆 | V1-V6 |
| `safety_nodes.py` | 输入过滤、输出审核 | V3 |
| `tool_nodes.py` | 工具调用 | V6 |
| `routing_nodes.py` | 条件路由 | V3-V6 |

```python
from app.graph import (
    load_context_node,
    generate_reply_simple_node,
    safety_in_node,
)
```

### 3. **工作流** (`graph/workflows/`)

主聊天工作流集成所有功能：

```python
from app.graph import graph

# 使用图
result = await graph.ainvoke({
    "messages": [HumanMessage(content="你好")],
    "user_id": "user123",
    "conversation_id": "conv456"
})
```

### 4. **配置管理** (`config.py`)

统一管理所有配置：

```python
from app import (
    get_llm_model,  # 获取LLM模型
    get_system_prompt,  # 获取当前人设
    MEMORY_MAX_ITEMS,  # 记忆保留数量
)
```

### 5. **工具封装** (`tools/external_tools.py`)

外部工具统一接口：

```python
from app import run_tool

# 调用工具
result = run_tool("get_weather", {"city": "北京"})
result = run_tool("get_time", {})
```

### 6. **记忆存储** (`memory/session_store.py`)

记忆管理类：

```python
from app import SimpleMemoryStore

# 获取记忆
memories = SimpleMemoryStore.get_short_term_memory("user123", "conv456")

# 保存记忆
SimpleMemoryStore.add_memory("user123", "conv456", "用户喜欢猫")
```

---

## 🔄 迁移指南

### 从旧版本迁移到重构版本

1. **导入路径变更**

```python
# 旧版本
from simple_chat import get_model
from memory_store import SimpleMemoryStore

# 新版本
from app.graph import get_model
from app import SimpleMemoryStore
```

2. **配置管理**

```python
# 旧版本 - 硬编码
SYSTEM_PROMPT = """..."""

# 新版本 - 配置化
from app import get_system_prompt

prompt = get_system_prompt()  # 自动加载人设
```

3. **工作流使用**

```python
# 旧版本
from pipeline_chat_v6 import graph

# 新版本
from app.graph import graph
```

---

## 🧪 测试

### 运行测试（待实现）

```bash
cd src/app/tests
python -m pytest test_graph_chat.py
```

---

## 📝 开发指南

### 添加新节点

1. 在 `src/app/graph/nodes/` 创建文件
2. 定义节点函数（签名: `async def node_name(state, config=None) -> Dict`）
3. 在 `nodes/__init__.py` 导出
4. 在工作流中使用

### 添加新工具

1. 在 `src/app/tools/external_tools.py` 定义工具函数
2. 在 `run_tool()` 添加路由
3. 更新 `AVAILABLE_TOOLS` 注册表

### 添加新人设

1. 在 `src/app/prompts/personas/` 创建 `.md` 文件
2. 编写人设内容
3. 设置环境变量 `PERSONA_NAME=新人设名`

---

## 🎯 下一步计划

- [ ] 实现测试用例
- [ ] 添加更多工具集成
- [ ] 实现向量存储 (`memory/vector_store.py`)
- [ ] 添加 FastAPI 服务入口 (`main.py`)
- [ ] 实现管理工作流 (`workflows/admin_workflow.py`)
- [ ] 完善配置文件 (`.env.example`)

---

## 📚 相关文档

- **[V6_ARCHITECTURE.md](./V6_ARCHITECTURE.md)** - V6 架构文档
- **[PERSONA_CONFIG.md](./PERSONA_CONFIG.md)** - 人设配置指南
- **[API_DOCS.md](./API_DOCS.md)** - API 文档
- **[QUICK_START.md](./QUICK_START.md)** - 快速启动指南

---

**重构完成日期**: 2025-12-10  
**状态**: ✅ 基础架构完成，功能待验证

