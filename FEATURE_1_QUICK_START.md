# 🚀 特性一快速启动指南

## 快速验证功能

### 方法 1: 使用 Gradio 前端测试

```bash
# 1. 启动所有服务
./run_with_monitor.sh

# 2. 打开 Gradio 前端
# http://127.0.0.1:7860

# 3. 测试对话
输入: 你好，我是小明
AI: [回复]

# 4. 测试清空指令
输入: /clear
AI: ✅ **对话历史已清空**...

# 5. 验证确实清空了
输入: 我叫什么名字？
AI: [不记得之前的"小明"]
```

---

### 方法 2: 使用自动化测试脚本

```bash
# 运行测试
python test_system_commands.py

# 预期输出:
# ✅ 所有测试通过！
```

---

### 方法 3: 直接调用 API

```bash
# 1. 启动 LangGraph 服务
langgraph dev --host 0.0.0.0 --port 2024

# 2. 发送清空指令
curl -X POST "http://127.0.0.1:2024/threads/test-123/runs/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "agent",
    "input": {
      "messages": [{"role": "user", "content": "/clear"}],
      "user_id": "test_user"
    },
    "stream_mode": ["messages"]
  }'

# 预期响应:
# event: messages
# data: {"content": "✅ **对话历史已清空**..."}
```

---

## 支持的指令列表

| 指令 | 功能 | 示例 |
|------|------|------|
| `/clear` | 清空对话历史 | `User: /clear` |
| `/reset` | 同 `/clear` | `User: /reset` |
| `清空对话` | 中文清空指令 | `User: 清空对话` |
| `/help` | 显示帮助 | `User: /help` |
| `/?` | 同 `/help` | `User: /?` |
| `帮助` | 中文帮助指令 | `User: 帮助` |

---

## 验证清单

- [ ] 启动服务成功
- [ ] 正常对话功能正常
- [ ] `/clear` 指令响应正确
- [ ] 清空后对话确实被重置
- [ ] `/help` 指令显示帮助信息
- [ ] 中文指令正常工作
- [ ] 监控面板显示正确

---

## 故障排查

### 问题 1: 指令无效果

**症状**: 输入 `/clear` 但 AI 把它当成普通消息

**解决**:
```bash
# 检查工作流是否正确编译
python3 << EOF
from src.app.graph.workflows.chat_workflow import graph
print("工作流编译成功")
EOF
```

### 问题 2: 导入错误

**症状**: `ModuleNotFoundError: No module named 'app'`

**解决**:
```bash
# 运行修复脚本
./fix_imports.sh
```

### 问题 3: LangGraph 未启动

**症状**: API 连接失败

**解决**:
```bash
# 检查服务是否运行
curl http://127.0.0.1:2024/ok

# 如果失败，重新启动
langgraph dev --host 0.0.0.0 --port 2024
```

---

## 监控和调试

### 查看实时日志

```bash
# 查看 LangGraph 日志
tail -f .langgraph_api/logs/langgraph.log

# 查看节点执行顺序
# 应该看到: load_context → check_system_command → reset_conversation
```

### 使用监控面板

```
http://127.0.0.1:8080

Thread ID: test-123

Messages:
  User: /clear
  AI: ✅ 对话历史已清空...

Short-term Memory: []  ← 确认已清空
Emotion: neutral       ← 确认已重置
```

---

## 下一步

功能验证成功后，可以：

1. **集成到 iMessage**
   - 用户直接在消息框输入 `/clear`

2. **添加更多指令**
   - 参考 `system_nodes.py` 扩展

3. **实现特性二**
   - 提示词管理平台
   - 人设切换功能

---

**文档版本**: 1.0  
**最后更新**: 2024-12-10

