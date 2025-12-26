# 特性二：提示词管理平台

## 功能概述

提示词管理平台允许管理员和用户管理多个AI人格/提示词，并在对话中灵活切换。

### 核心功能

1. **提示词管理（CRUD）**
   - 创建、查看、编辑、删除提示词
   - 从文件导入提示词
   - 查看所有提示词列表

2. **用户提示词关联**
   - 用户可以选择激活的提示词
   - 系统自动加载用户的个性化提示词
   - 支持动态切换

3. **系统指令支持**
   - `/personas` - 查看可用提示词列表
   - `/persona <名称>` - 切换到指定提示词
   - `切换人设 <名称>` - 切换提示词（中文）

---

## 架构设计

### 数据库结构

**personas 表**（提示词）:
```sql
- id (INTEGER PRIMARY KEY)
- name (TEXT UNIQUE) - 提示词名称
- content (TEXT) - 提示词内容
- description (TEXT) - 描述
- created_at (TIMESTAMP)
- updated_at (TIMESTAMP)
```

**user_personas 表**（用户-提示词关联）:
```sql
- user_id (TEXT)
- persona_id (INTEGER)
- is_active (BOOLEAN) - 是否激活
- created_at (TIMESTAMP)
- PRIMARY KEY (user_id, persona_id)
```

### 核心组件

1. **PromptService** (`src/app/prompts/prompt_service.py`)
   - 提供提示词的CRUD操作
   - 管理用户与提示词的关联
   - 支持从文件导入提示词

2. **系统节点** (`src/app/graph/nodes/system_nodes.py`)
   - `list_personas_node` - 列出可用提示词
   - `switch_persona_node` - 切换用户提示词

3. **记忆节点** (`src/app/graph/nodes/memory_nodes.py`)
   - `load_context_node` - 加载用户的active persona

4. **LLM节点** (`src/app/graph/nodes/llm_nodes.py`)
   - 优先使用 `state.current_persona`
   - 回退到默认提示词

---

## 快速开始

### 1. 初始化数据库并导入提示词

```bash
cd /path/to/my_langgraph_app
python import_personas.py
```

输出示例:
```
✅ 成功导入: 云朵 (ID: 1)
✅ 成功导入: 由此 (ID: 2)
```

### 2. 启动提示词管理平台

```bash
python prompt_admin_app.py
```

访问: `http://127.0.0.1:7861`

功能:
- 📋 查看提示词 - 查看所有已创建的提示词
- 🔍 查看详情 - 查看单个提示词的完整内容
- ➕ 创建提示词 - 手动创建新的提示词
- ✏️ 编辑提示词 - 修改现有提示词
- 🗑️ 删除提示词 - 删除不需要的提示词
- 📥 导入提示词 - 从 .txt 或 .md 文件导入

### 3. 启动LangGraph服务和聊天界面

```bash
./run_with_monitor.sh
```

或手动启动:
```bash
# 启动 LangGraph 后端
langgraph dev --host 0.0.0.0 --port 2024 --allow-blocking &

# 启动 Gradio 前端
python gradio_app.py &

# 启动监控面板（可选）
python gradio_monitor_app_v2.py &
```

### 4. 在聊天中使用

#### 查看可用提示词
```
输入: /personas
或: 提示词列表

AI回复:
📋 可用提示词列表

• 云朵 - 名为"云朵"的AI物种...
• 由此 - 一位名为「由此」的"拼图伙伴"...

共 2 个提示词可用。
```

#### 切换提示词
```
输入: /persona 云朵
或: 切换人设 云朵

AI回复:
✅ 已切换到提示词: 云朵

名为"云朵"的AI物种，无性别，以网络信息为"食物"...

从现在开始，我会以新的人格与你对话。
```

#### 验证切换
```
用户: 你好
AI (云朵人格): 嘿，又见面啦~☁️ ... (温和诗意风格)
```

```
输入: /persona 由此

用户: 你好
AI (由此人格): 你好，欢迎来到「由此」... (拼图伙伴风格)
```

---

## 使用场景

### 场景1: 管理员创建新提示词

1. 打开提示词管理平台 `http://127.0.0.1:7861`
2. 切换到 "➕ 创建提示词" 标签
3. 填写:
   - 名称: `小助手`
   - 描述: `专业的技术助手`
   - 内容: `你是一个专业的技术助手...`
4. 点击"创建"

### 场景2: 用户切换提示词

在聊天界面:
```
1. 输入 /personas 查看可用提示词
2. 输入 /persona 小助手 切换
3. 开始对话，AI 使用新的人格回复
```

### 场景3: 从文件批量导入

1. 准备 `my_persona.md` 文件
2. 在管理平台切换到 "📥 导入提示词"
3. 填写名称和描述
4. 上传文件
5. 点击"导入"

---

## 工作流程

### 用户切换提示词流程

```
用户输入: /persona 云朵
  ↓
check_system_command() 检测到 "switch_persona"
  ↓
switch_persona_node()
  ├─ 从数据库查找 "云朵" persona
  ├─ 设置 user_personas 关联（is_active=1）
  ├─ 清空对话历史和记忆（重新开始）
  └─ 返回成功消息
  ↓
下次对话:
  ↓
load_context_node()
  ├─ 加载短期记忆
  ├─ 查询用户的 active persona
  └─ 将 persona.content 存入 state.current_persona
  ↓
generate_reply_simple_node()
  ├─ 检查 state.current_persona
  ├─ 如果存在，使用个性化提示词
  └─ 否则，使用默认提示词
  ↓
AI 以新人格回复
```

### 提示词优先级

1. **最高优先级**: `state.current_persona`（用户选择的提示词）
2. **次优先级**: 默认提示词（通过 `PERSONA_NAME` 环境变量）
3. **回退**: 内置默认提示词

---

## 文件清单

### 新增文件

```
src/app/prompts/
├── __init__.py
└── prompt_service.py        # 提示词服务（CRUD）

src/app/graph/nodes/
└── system_nodes.py           # 系统节点（已扩展）

prompt_admin_app.py           # 提示词管理平台（Gradio UI）
import_personas.py            # 导入现有提示词脚本
prompts.db                    # SQLite数据库（自动创建）
FEATURE_2_PROMPT_PLATFORM.md  # 本文档
```

### 修改文件

```
src/app/graph/nodes/
├── __init__.py               # 导出新节点
├── memory_nodes.py           # 加载用户提示词
└── llm_nodes.py              # 使用个性化提示词

src/app/graph/workflows/
└── chat_workflow.py          # 添加提示词路由

app/config.py                 # 添加 BASE_DIR
```

---

## API 参考

### PromptService API

```python
from app import prompt_service

# 创建提示词
persona_id = prompt_service.create_persona(
    name="助手",
    content="你是一个...",
    description="描述"
)

# 获取提示词
persona = prompt_service.get_persona_by_name("云朵")
persona = prompt_service.get_persona_by_id(1)

# 列出所有提示词
personas = prompt_service.list_personas()

# 更新提示词
prompt_service.update_persona(
    persona_id=1,
    name="新名称",
    content="新内容"
)

# 删除提示词
prompt_service.delete_persona(persona_id=1)

# 设置用户提示词
prompt_service.set_user_persona(
    user_id="user123",
    persona_id=1
)

# 获取用户当前提示词
active_persona = prompt_service.get_user_active_persona("user123")

# 从文件导入
persona_id = prompt_service.import_persona_from_file(
    name="导入的",
    filepath=Path("prompt.md"),
    description="描述"
)
```

---

## 故障排查

### 问题1: 数据库不存在
**症状**: `no such table: personas`
**解决**: 重新运行 `python import_personas.py` 初始化数据库

### 问题2: 提示词未生效
**症状**: 切换提示词后，AI 仍使用旧人格
**检查**:
1. LangGraph 日志: `✅ 已为用户 xxx 加载提示词`
2. LangGraph 日志: `✅ 使用个性化提示词`
3. 确认用户ID一致

**解决**: 重启 LangGraph 服务

### 问题3: 管理平台无法打开
**症状**: `Address already in use`
**解决**: 
```bash
# 查找占用端口的进程
lsof -i :7861
# 杀掉进程
kill -9 <PID>
```

---

## 最佳实践

### 1. 提示词命名
- ✅ 使用简短、清晰的名称（如"云朵"、"助手"）
- ✅ 避免特殊字符和空格
- ❌ 不要使用过长的名称

### 2. 提示词内容
- ✅ 包含明确的人格定位和行为准则
- ✅ 使用 Markdown 格式化（清晰可读）
- ✅ 包含示例对话（如果需要）
- ❌ 不要包含敏感信息

### 3. 用户体验
- ✅ 提供清晰的提示词描述
- ✅ 切换提示词后清空历史（避免混淆）
- ✅ 在管理平台提供预览功能

### 4. 数据管理
- ✅ 定期备份 `prompts.db`
- ✅ 版本控制提示词文件（`.md`）
- ✅ 定期清理无用提示词

---

## 扩展方向

### 短期扩展
- [ ] 提示词版本管理
- [ ] 提示词导出功能
- [ ] 提示词使用统计
- [ ] 用户提示词收藏

### 长期扩展
- [ ] 提示词模板库
- [ ] 提示词评分系统
- [ ] 社区提示词分享
- [ ] 基于用户反馈的自动优化

---

## 贡献者

- 功能设计与实现: AI Assistant
- 产品需求: 用户

---

## 更新日志

### v1.0.0 (2025-12-10)
- ✅ 初始版本
- ✅ 提示词CRUD功能
- ✅ Gradio管理界面
- ✅ 系统指令支持（/persona, /personas）
- ✅ 动态提示词加载
- ✅ 导入云朵和由此提示词

---

## 相关文档

- [系统指令文档](SYSTEM_COMMANDS.md)
- [特性一快速开始](FEATURE_1_QUICK_START.md)
- [API文档](API_DOCS.md)

