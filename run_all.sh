#!/bin/bash

# 配置
BACKEND_PORT=2024
FRONTEND_PORT=7860
VENV_PATH="../.venv/bin/activate"

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 清理端口函数
cleanup_port() {
    local PORT=$1
    echo -e "${YELLOW}Checking port $PORT...${NC}"
    PID=$(lsof -ti :$PORT)
    if [ -n "$PID" ]; then
        echo -e "${YELLOW}Port $PORT is in use by PID $PID. Killing it...${NC}"
        kill -9 $PID
    else
        echo -e "${GREEN}Port $PORT is free.${NC}"
    fi
}

# 退出处理函数
cleanup_all() {
    echo -e "\n${RED}Stopping all services...${NC}"
    kill $(jobs -p) 2>/dev/null
    cleanup_port $BACKEND_PORT
    cleanup_port $FRONTEND_PORT
    echo -e "${GREEN}All services stopped.${NC}"
    exit
}

# 注册信号处理（Ctrl+C）
trap cleanup_all SIGINT

# 1. 清理旧进程
echo -e "${GREEN}=== Cleaning up old processes ===${NC}"
cleanup_port $BACKEND_PORT
cleanup_port $FRONTEND_PORT

# 2. 激活虚拟环境
if [ -f "$VENV_PATH" ]; then
    echo -e "${GREEN}Activating virtual environment...${NC}"
    source "$VENV_PATH"
else
    echo -e "${RED}Error: Virtual environment not found at $VENV_PATH${NC}"
    exit 1
fi

# 3. 启动后端
echo -e "${GREEN}=== Starting LangGraph Backend ===${NC}"
langgraph dev --host 0.0.0.0 --port $BACKEND_PORT --no-browser &
BACKEND_PID=$!
echo -e "Backend started with PID $BACKEND_PID"

# 等待后端启动 (简单的等待几秒，或者可以用 curl 检测)
echo -e "${YELLOW}Waiting for backend to be ready...${NC}"
sleep 5

# 4. 启动前端
echo -e "${GREEN}=== Starting Gradio Frontend ===${NC}"
python gradio_app.py

# 脚本会停在这里等待前端结束，因为 python gradio_app.py 是前台运行的
# 如果前端退出了，我们也清理后端
cleanup_all




