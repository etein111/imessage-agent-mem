# LangGraph 简单聊天示例

这是一个简单的 LangGraph 聊天机器人示例，展示了如何启动 LangGraph 开发服务器。

## 运行步骤

### 1. 激活虚拟环境

```bash
cd /Users/weitianyi/Desktop/xbuddy/langgraph
source .venv/bin/activate
```

### 2. 进入项目目录

```bash
cd my_langgraph_app
```

### 3. 启动开发服务器

```bash
langgraph dev
```

默认情况下，服务器会：
- 在 `http://127.0.0.1:2024` 启动
- 自动打开浏览器（可以使用 `--no-browser` 禁用）
- 支持热重载（代码修改后自动重启）

### 4. 访问前端界面

启动后，浏览器会自动打开 LangGraph Studio 界面，你可以：
- 查看和测试你的 graph
- 与聊天机器人对话
- 查看执行流程和状态

## 配置选项

### 使用自定义端口

```bash
langgraph dev --port 8000
```

### 禁用自动打开浏览器

```bash
langgraph dev --no-browser
```

### 使用 OpenAI API（可选）

如果要使用真实的 GPT 模型，需要设置环境变量：

```bash
export OPENAI_API_KEY=your-api-key-here
langgraph dev
```

或者创建 `.env` 文件：

```
OPENAI_API_KEY=your-api-key-here
```

## API 端点

服务器启动后，你可以通过以下方式访问：

- **前端界面**: http://127.0.0.1:2024
- **API 文档**: http://127.0.0.1:2024/docs
- **健康检查**: http://127.0.0.1:2024/health

## 测试 API

你可以使用 curl 测试 API：

```bash
# 创建新的对话线程
curl -X POST http://127.0.0.1:2024/threads

# 发送消息
curl -X POST http://127.0.0.1:2024/threads/{thread_id}/runs \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "simple_chat",
    "input": {
      "messages": [{"role": "user", "content": "你好！"}]
    }
  }'
```

## 使用 Docker 运行（推荐用于联调）

可以使用仓库根目录下提供的 `Dockerfile` 将整个 Agent 后端打包成容器：

```bash
# 在仓库根目录执行
docker build -t cloud-buddy .

# 运行容器，并将必要的环境变量（如 Google Vertex AI 凭证）传入
docker run \
  -p 2024:2024 \
  -e GOOGLE_CLOUD_PROJECT=your-project \
  -e GOOGLE_CLOUD_LOCATION=us-central1 \
  -e GOOGLE_APPLICATION_CREDENTIALS=/app/credentials.json \
  -v $HOME/.config/gcloud/application_default_credentials.json:/app/credentials.json:ro \
  cloud-buddy
```

容器启动后，可以通过 `http://localhost:2024` 访问 LangGraph API，以及 `/docs` 接口文档。


