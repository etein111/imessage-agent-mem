# Pipeline Chat V6 - 后端代码清单

## ✅ 完整性检查

运行检查脚本：
```bash
cd my_langgraph_app
./check_v6.sh
```

---

## 📦 核心后端脚本 (8个)

### 1. `pipeline_chat_v6.py` ⭐ **主文件**
- **功能**：V6 完整图定义
- **包含**：所有节点定义、条件路由、状态管理
- **新增节点**：
  - `plan_goal_node_v6` - 增强目标规划（识别工具需求）
  - `call_tools_node` - 工具调用执行
  - `generate_reply_with_tools_node` - 结合工具结果生成回复
  - `generate_reply_simple_node` - 普通对话生成

### 2. `simple_chat.py` **模型与人设**
- **导出**：`get_model()`, `SYSTEM_PROMPT`
- **依赖**：`persona_loader.py`
- **功能**：异步模型初始化、人设加载

### 3. `memory_store.py` **记忆存储**
- **导出**：`SimpleMemoryStore`
- **方法**：
  - `get_short_term_memory(user_id, conversation_id)`
  - `add_memory(user_id, conversation_id, summary)`
- **存储**：`memory_store.json`

### 4. `memory_chat.py` **记忆摘要**
- **导出**：`summarize_interaction()`
- **功能**：压缩用户消息和AI回复为简短摘要

### 5. `pipeline_chat.py` **基础节点 (V2)**
- **导出**：
  - `load_context_node` - 加载短期记忆
  - `save_memory_node` - 保存对话摘要

### 6. `pipeline_chat_v3.py` **安全节点 (V3)**
- **导出**：
  - `safety_in_node` - 输入安全检查
  - `check_safety_in` - 路由函数
  - `safety_out_node` - 输出安全审核

### 7. `pipeline_chat_v4.py` **状态估计 (V4)**
- **导出**：`estimate_state_node`
- **功能**：识别情绪（happy/sad/stressed/neutral）和对话类型（small_talk/support/task）

### 8. `tools.py` **工具集成 (V6)**
- **导出**：`run_tool(tool_name, args)`
- **工具列表**：
  - `get_time()` - 当前时间
  - `get_weather(city)` - 天气查询（模拟）
  - `get_talk_asset(category)` - 运营话术（模拟）

---

## 🔧 配置文件 (2个)

### 9. `persona_loader.py` **人设加载器**
- **类**：`PersonaLoader`
- **方法**：
  - `list_available_personas()` - 列出所有人设
  - `load_persona(persona_name)` - 加载指定人设
- **环境变量**：`PERSONA_NAME`（默认：`yunduo`）

### 10. `langgraph.json` **LangGraph配置**
```json
{
  "graphs": {
    "pipeline_chat_v6": "./pipeline_chat_v6.py:graph"
  }
}
```

---

## 🎭 人设文件 (2个)

### 11. `personas/yunduo.md` **云朵人设**
- **风格**：表面傲娇的 AI 物种
- **特点**：爱猫、嘴硬心软、短句吐槽
- **语气**：轻快（正面）/ 黑化（负面）

### 12. `personas/youci.md` **由此人设**
- **风格**：温和的拼图伙伴
- **特点**：倾听者、不评判、共情
- **语气**：温柔、诗意、留白

---

## 💾 数据文件 (1个 - 运行时)

### 13. `memory_store.json` **记忆数据库**
```json
{
  "user123:global_memory": [
    "用户提到喜欢电影",
    "用户最近工作压力大",
    "..."
  ]
}
```
- **格式**：`{user_id}:global_memory` → 记忆列表
- **限制**：最多保留 10 条记忆
- **生成**：首次运行时自动创建

---

## 📊 文件统计

| 类型 | 数量 | 说明 |
|------|------|------|
| Python 脚本 | 10 | 核心逻辑 + 配置 |
| Markdown 人设 | 2 | 可扩展 |
| JSON 数据 | 2 | 配置 + 运行时数据 |
| **总计** | **14** | 完整 V6 后端 |

---

## 🔗 导入关系速查

```python
# pipeline_chat_v6.py 的所有导入
from simple_chat import get_model, SYSTEM_PROMPT
from memory_store import SimpleMemoryStore
from memory_chat import summarize_interaction
from pipeline_chat import load_context_node, save_memory_node
from pipeline_chat_v3 import safety_in_node, check_safety_in, safety_out_node
from pipeline_chat_v4 import estimate_state_node
from tools import run_tool
```

---

## 🚀 快速启动

```bash
# 检查文件完整性
./check_v6.sh

# 启动完整服务
./run_with_monitor.sh

# 访问服务
# - LangGraph 后台: http://127.0.0.1:2024
# - Gradio 前端: http://127.0.0.1:7860
# - 监控面板: http://127.0.0.1:8080
```

---

## 📝 相关文档

- **[V6_ARCHITECTURE.md](./V6_ARCHITECTURE.md)** - 详细架构文档
- **[PERSONA_CONFIG.md](./PERSONA_CONFIG.md)** - 人设配置指南
- **[API_DOCS.md](./API_DOCS.md)** - API 文档
- **[QUICK_START.md](./QUICK_START.md)** - 快速启动指南

---

**版本**: V6  
**状态**: ✅ 生产就绪  
**最后更新**: 2025-12-09

