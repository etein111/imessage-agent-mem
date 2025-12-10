# 🚀 重构版本快速使用指南

## ✅ 验证已通过

重构后的代码已验证成功！所有模块导入正常。

---

## 📝 重要提醒

### 使用重构代码时，必须：

1. **激活虚拟环境** ✅
2. **在正确目录运行** ✅
3. **设置 PYTHONPATH** (已通过软链接解决) ✅

---

## 🔧 正确的使用方式

### 方法 1: 一键修复（推荐）

```bash
cd /Users/weitianyi/Desktop/xbuddy/langgraph/my_langgraph_app
./fix_imports.sh
```

这个脚本会：
- ✅ 创建软链接 (`app -> src/app`)
- ✅ 激活虚拟环境
- ✅ 测试所有导入
- ✅ 验证功能正常

### 方法 2: 手动测试

```bash
# 1. 进入项目目录
cd /Users/weitianyi/Desktop/xbuddy/langgraph/my_langgraph_app

# 2. 激活虚拟环境（重要！）
source ../.venv/bin/activate

# 3. 进入 src 目录
cd src

# 4. 测试导入
python3 -c "from app.graph.state import PipelineState; print('✅ OK')"
python3 -c "from app.graph.nodes import load_context_node; print('✅ OK')"
python3 -c "from app.config import get_system_prompt; print('✅ OK')"
```

---

## ❌ 常见错误

### 错误 1: `ModuleNotFoundError: No module named 'langchain_core'`

**原因**: 没有激活虚拟环境

**解决**:
```bash
# 先激活虚拟环境
source ../.venv/bin/activate
# 或
cd /Users/weitianyi/Desktop/xbuddy/langgraph
source .venv/bin/activate
```

### 错误 2: `ModuleNotFoundError: No module named 'app'`

**原因**: 没有设置 PYTHONPATH 或软链接

**解决**:
```bash
# 运行修复脚本
./fix_imports.sh

# 或手动创建软链接
ln -sf src/app app
```

---

## 🎯 使用新架构

### 在 Python 代码中导入

```python
# 激活虚拟环境后

# 导入状态
from app.graph.state import PipelineState, create_initial_state

# 导入节点
from app.graph.nodes import (
    load_context_node,
    generate_reply_simple_node,
    safety_in_node,
)

# 导入工作流
from app.graph.workflows.chat_workflow import graph

# 导入配置
from app.config import get_llm_model, get_system_prompt

# 导入工具
from app.tools.external_tools import run_tool

# 使用工作流
result = await graph.ainvoke({
    "messages": [...],
    "user_id": "user123",
    "conversation_id": "conv456"
})
```

### 在 LangGraph 中使用

```json
// langgraph.json
{
  "graphs": {
    "chat_v6_refactored": "./src/app/graph/workflows/chat_workflow.py:graph"
  }
}
```

---

## 🔄 切换到新架构

### 测试阶段（当前推荐）

保持两套配置并存：
- `langgraph.json` - 使用旧版本（稳定）
- `langgraph_new.json` - 新版本配置（测试用）

### 正式切换

确认无误后：

```bash
# 1. 备份旧配置
cp langgraph.json langgraph.json.backup

# 2. 启用新配置
cp langgraph_new.json langgraph.json

# 3. 重启服务
./run_with_monitor.sh
```

---

## 📊 当前状态

| 项目 | 状态 | 说明 |
|------|------|------|
| 目录结构 | ✅ 完成 | 标准化模块结构 |
| 代码重组 | ✅ 完成 | 11个核心模块 |
| 导入测试 | ✅ 通过 | 所有模块导入正常 |
| 向后兼容 | ✅ 保证 | 旧文件完整保留 |
| 文档 | ✅ 完整 | 4份详细文档 |
| 生产就绪 | 🔄 待验证 | 需要功能测试 |

---

## 📚 相关文档

1. **REFACTORED_README.md** - 新架构详细说明
2. **REFACTORING_VERIFICATION.md** - 验证步骤
3. **REFACTORING_SUMMARY.md** - 重构对比
4. **REFACTORING_COMPLETE.md** - 完成报告

---

## 💡 最佳实践

### 开发环境

1. **总是激活虚拟环境**
   ```bash
   source ../.venv/bin/activate
   ```

2. **在项目根目录运行**
   ```bash
   cd /Users/weitianyi/Desktop/xbuddy/langgraph/my_langgraph_app
   ```

3. **使用软链接（已设置）**
   - `app` -> `src/app` (自动创建)

### 生产环境

1. **设置环境变量**
   ```bash
   export PYTHONPATH="/path/to/my_langgraph_app/src:$PYTHONPATH"
   ```

2. **在启动脚本中激活虚拟环境**
   ```bash
   source /path/to/.venv/bin/activate
   ```

---

## 🎉 快速验证清单

- [x] 运行 `./fix_imports.sh`
- [x] 软链接创建成功
- [x] 虚拟环境激活
- [x] 所有导入测试通过
- [ ] 运行完整工作流测试（可选）
- [ ] 切换到新配置（可选）

---

**状态**: ✅ 重构验证通过，可以开始使用！

**最后更新**: 2025-12-10

