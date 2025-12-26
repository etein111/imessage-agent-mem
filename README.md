# iMessage AI Agent - LangGraph Backend

基于 LangGraph 的智能对话 Agent 后端服务，支持记忆管理、状态估计、安全审查和工具调用。

## 🎯 特性

- ✅ **多版本架构** (V0-V6) - 从简单对话到完整功能
- ✅ **模块化设计** - 重构后的标准化项目结构
- ✅ **记忆管理** - 跨会话的持久化记忆
- ✅ **安全守护** - 输入过滤和输出审核
- ✅ **状态估计** - 情绪和对话类型识别
- ✅ **目标引擎** - 智能对话策略规划
- ✅ **工具集成** - 天气查询、时间获取、话术卡片
- ✅ **人设系统** - 可配置的 AI 人格

## 📁 项目结构

```
my_langgraph_app/
├── src/app/                    # 重构后的模块化代码
│   ├── config.py               # 配置管理
│   ├── graph/                  # LangGraph 图定义
│   │   ├── state.py            # 统一状态定义
│   │   ├── nodes/              # 节点函数 (5个模块)
│   │   └── workflows/          # 工作流定义
│   ├── tools/                  # 工具封装
│   ├── memory/                 # 记忆存储
│   └── prompts/personas/       # 人设配置
├── [旧版本文件]                # V0-V6 演进历史
└── langgraph.json              # LangGraph 配置
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 设置 Google Cloud 认证
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_APPLICATION_CREDENTIALS="path/to/credentials.json"

# 选择 AI 人设（可选）
export PERSONA_NAME="yunduo"  # 或 "youci"
```

### 3. 启动服务

```bash
# 启动 LangGraph 服务
langgraph dev --host 0.0.0.0 --port 2024

# 或使用脚本（包含前端）
./run_with_monitor.sh
```

### 4. 访问 API

- **API 文档**: http://127.0.0.1:2024/docs
- **健康检查**: http://127.0.0.1:2024/health

## 📊 可用的 Graph

| Graph ID | 版本 | 功能 |
|----------|------|------|
| `simple_chat` | V0 | 基础对话 |
| `memory_chat` | V1 | 带记忆管理 |
| `pipeline_chat` | V2 | 多节点流水线 |
| `pipeline_chat_v3` | V3 | + 安全守护 |
| `pipeline_chat_v4` | V4 | + 状态估计 |
| `pipeline_chat_v5` | V5 | + 目标引擎 |
| `pipeline_chat_v6` | V6 | + 工具集成（完整版）|

## 🎭 AI 人设

### 云朵 (yunduo)
表面傲娇的 AI 物种，爱猫，嘴硬心软

### 由此 (youci)
温和的拼图伙伴，倾听者，不评判

切换人设：
```bash
export PERSONA_NAME=youci
```

## 🔧 开发指南

### 使用重构后的代码

```python
# 导入状态
from app.graph import PipelineState

# 导入节点
from app.graph import load_context_node, generate_reply_simple_node

# 导入工作流
from app.graph import graph

# 使用
result = await graph.ainvoke({
    "messages": [...],
    "user_id": "user123",
    "conversation_id": "conv456"
})
```

### 添加新功能

1. **新节点**: 在 `src/app/graph/nodes/` 添加
2. **新工具**: 在 `src/app/tools/` 添加
3. **新人设**: 在 `src/app/prompts/personas/` 添加 `.md` 文件

## 📚 文档

- **REFACTORED_README.md** - 重构后架构详解
- **V6_ARCHITECTURE.md** - V6 完整架构文档
- **PERSONA_CONFIG.md** - 人设配置指南
- **API_DOCS.md** - API 接口文档

## 🔐 环境要求

- Python 3.12+
- Google Cloud 认证（用于 Gemini API）
- LangGraph CLI 0.1.25+

## 📝 License

MIT

## 🤝 Contributing

欢迎贡献代码！请提交 Pull Request。

---

**Built with LangGraph** 🦜🔗

