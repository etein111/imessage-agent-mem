# 👥 团队成员快速设置指南

## 🚀 快速开始（5分钟）

### 步骤 1: 克隆仓库

```bash
git clone git@github.com:x-buddy/imessage-agent.git
cd imessage-agent
```

### 步骤 2: 安装依赖

```bash
# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 步骤 3: 配置环境变量

```bash
# 复制环境变量模板
cp env.example .env

# 编辑 .env 文件，填入你的配置
nano .env
```

**必填项**：
```bash
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/credentials.json
```

**可选项**：
```bash
PERSONA_NAME=yunduo  # 或 youci
LLM_MODEL=gemini-2.0-flash-exp
LLM_TEMPERATURE=0.7
```

### 步骤 4: 修复导入路径

```bash
# 运行自动修复脚本
./fix_imports.sh
```

这会：
- ✅ 创建软链接 (`app -> src/app`)
- ✅ 激活虚拟环境
- ✅ 测试所有导入

### 步骤 5: 启动服务

```bash
# 仅启动后端
langgraph dev --host 0.0.0.0 --port 2024

# 访问 API 文档
open http://127.0.0.1:2024/docs
```

---

## 📚 重要文档

克隆后必读：

1. **README.md** - 项目总览
2. **QUICK_START.md** - 快速启动指南
3. **V6_ARCHITECTURE.md** - 完整架构文档
4. **REFACTORED_README.md** - 重构后架构说明

---

## 🎭 选择 AI 人设

### 云朵 (yunduo) - 默认
表面傲娇的 AI 物种，爱猫

### 由此 (youci)
温和的拼图伙伴，倾听者

**切换方式**：
```bash
export PERSONA_NAME=youci
```

---

## 🔧 常见问题

### Q1: 导入错误 `ModuleNotFoundError: No module named 'app'`

**解决**：
```bash
./fix_imports.sh
```

### Q2: 导入错误 `ModuleNotFoundError: No module named 'langchain_core'`

**解决**：激活虚拟环境
```bash
source .venv/bin/activate
```

### Q3: Google Cloud 认证失败

**解决**：
1. 确保 `GOOGLE_APPLICATION_CREDENTIALS` 路径正确
2. 确保服务账号有 Vertex AI 权限
3. 运行 `gcloud auth application-default login`

---

## 🧪 测试安装

```bash
# 激活虚拟环境
source .venv/bin/activate

# 测试导入
cd src
python3 -c "from app.graph.workflows.chat_workflow import graph; print('✅ 工作流加载成功')"

# 测试人设加载
python3 -c "from app.config import get_system_prompt; print('✅ 人设加载成功')"
```

---

## 📡 API 使用

### 发送消息

```bash
# POST /threads/{thread_id}/runs/stream
curl -X POST "http://127.0.0.1:2024/threads/test-thread/runs/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "agent",
    "input": {
      "messages": [{"role": "user", "content": "你好"}],
      "user_id": "test_user"
    },
    "stream_mode": ["messages"]
  }'
```

详见：**API_DOCS.md**

---

## 🛠️ 开发工作流

### 1. 创建新分支

```bash
git checkout -b feature/your-feature
```

### 2. 开发和测试

```bash
# 修改代码
# ...

# 测试
./fix_imports.sh
cd src && python3 -m pytest
```

### 3. 提交和推送

```bash
git add .
git commit -m "feat: Add new feature"
git push origin feature/your-feature
```

### 4. 创建 Pull Request

在 GitHub 上创建 PR

---

## 📞 获取帮助

- **文档**: 查看 `README.md` 和其他 `.md` 文档
- **Issues**: https://github.com/x-buddy/imessage-agent/issues
- **架构问题**: 查看 `V6_ARCHITECTURE.md` 和 `REFACTORED_README.md`

---

**欢迎加入团队！** 🎉

**仓库**: https://github.com/x-buddy/imessage-agent

