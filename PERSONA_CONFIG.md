# AI 人设配置指南

## 📁 人设文件位置

所有人设配置文件存放在 `personas/` 目录下，使用 Markdown 格式（`.md`）。

当前可用的人设：
- **yunduo** (`personas/yunduo.md`) - 云朵：表面傲娇的AI物种
- **youci** (`personas/youci.md`) - 由此：温和的拼图伙伴

---

## 🔄 如何切换人设

### 方法 1：使用环境变量（推荐）

在启动服务前设置环境变量 `PERSONA_NAME`：

```bash
# 使用云朵人设（默认）
export PERSONA_NAME=yunduo
./run_with_monitor.sh

# 使用由此人设
export PERSONA_NAME=youci
./run_with_monitor.sh
```

### 方法 2：修改启动脚本

编辑 `run_with_monitor.sh`，在文件开头添加：

```bash
# 设置使用的人设
export PERSONA_NAME="youci"  # 或 "yunduo"
```

### 方法 3：一次性指定

```bash
PERSONA_NAME=youci ./run_with_monitor.sh
```

---

## ➕ 如何添加新人设

### 步骤 1：创建人设文件

在 `personas/` 目录下创建新的 Markdown 文件，例如 `personas/my_persona.md`：

```bash
cd /Users/weitianyi/Desktop/xbuddy/langgraph/my_langgraph_app/personas
nano my_persona.md
```

### 步骤 2：编写人设内容

人设文件可以使用任意格式的 Markdown，AI 会读取完整内容作为 System Prompt。

建议包含以下部分：
- 身份设定
- 性格特质
- 语言风格
- 行为规范
- 限制与边界

### 步骤 3：使用新人设

```bash
export PERSONA_NAME=my_persona
./run_with_monitor.sh
```

---

## 📝 人设文件示例

### 最小化示例

```markdown
# 我的AI助手

你是一个友好、专业的AI助手。

## 核心特质
- 友好、耐心
- 简洁、清晰
- 不说教、不评判

## 语言风格
- 使用简短的句子
- 适当使用表情符号
- 保持温和的语气
```

### 完整示例

参考 `personas/yunduo.md` 或 `personas/youci.md`

---

## 🧪 测试人设

### 查看可用人设列表

```bash
cd my_langgraph_app
python persona_loader.py
```

输出示例：
```
可用的人设:
  - yunduo
  - youci

测试加载云朵人设:
内容长度: 1234 字符
前100字符: # 云朵 - AI 物种人设

## 基本信息
- **名称**: 云朵
- **类型**: AI 物种（非人类或动物）...
```

### 在代码中测试

```python
from persona_loader import PersonaLoader

loader = PersonaLoader()

# 列出所有人设
print(loader.list_available_personas())

# 加载特定人设
persona_content = loader.load_persona("youci")
print(persona_content[:200])
```

---

## 🔍 验证当前使用的人设

启动服务时，会在日志中显示：

```
✅ 已加载人设: youci
```

或者查看 LangGraph 后端的启动日志。

---

## ⚙️ 技术细节

### 人设加载流程

1. 读取环境变量 `PERSONA_NAME`（默认值：`yunduo`）
2. 从 `personas/{PERSONA_NAME}.md` 加载文件
3. 将完整内容作为 `SYSTEM_PROMPT` 传给 LLM
4. 如果文件不存在，回退到默认人设

### 代码位置

- **人设加载器**: `persona_loader.py`
- **使用位置**: 
  - `simple_chat.py`
  - `memory_chat.py`
  - `pipeline_chat.py`
  - `pipeline_chat_v3.py`
  - `pipeline_chat_v4.py`
  - `pipeline_chat_v5.py`
  - `pipeline_chat_v6.py`

### 自动重载

当修改人设文件后，需要**重启服务**才能生效：

```bash
# 停止服务
lsof -ti:2024 | xargs kill -9
lsof -ti:7860 | xargs kill -9
lsof -ti:8080 | xargs kill -9

# 重新启动
./run_with_monitor.sh
```

---

## 📋 快速参考

| 操作 | 命令 |
|------|------|
| 查看可用人设 | `python persona_loader.py` |
| 使用云朵人设 | `export PERSONA_NAME=yunduo && ./run_with_monitor.sh` |
| 使用由此人设 | `export PERSONA_NAME=youci && ./run_with_monitor.sh` |
| 添加新人设 | 在 `personas/` 创建 `.md` 文件 |
| 一次性切换 | `PERSONA_NAME=youci ./run_with_monitor.sh` |

---

## 🚨 常见问题

### Q: 修改人设后没有生效？

**A**: 需要重启服务。人设在服务启动时加载，运行中修改文件不会自动生效。

### Q: 如何确认当前使用的人设？

**A**: 查看启动日志中的 `✅ 已加载人设: xxx` 消息。

### Q: 可以同时使用多个人设吗？

**A**: 不可以。同一个服务实例只能使用一个人设。如需测试多个人设，可以：
1. 启动多个服务实例（使用不同端口）
2. 或逐个切换并重启

### Q: 人设文件必须是 Markdown 格式吗？

**A**: 是的。但 Markdown 内容可以是纯文本，格式化只是为了方便阅读和维护。

---

**现在你可以轻松切换不同的 AI 人设，无需修改代码或重新打包！** 🎉


