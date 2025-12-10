#!/bin/bash

# 配置
BACKEND_PORT=2024
FRONTEND_PORT=7860
MONITOR_PORT=8080
VENV_PATH="../.venv/bin/activate"

# AI 人设配置（可选，默认为 yunduo）
# 可用选项: yunduo（云朵）, youci（由此）
# 使用方法: export PERSONA_NAME=youci 或在下方取消注释
# export PERSONA_NAME="youci"
if [ -z "$PERSONA_NAME" ]; then
    export PERSONA_NAME="yunduo"
fi

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
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
    cleanup_port $MONITOR_PORT
    echo -e "${GREEN}All services stopped.${NC}"
    exit
}

# 注册信号处理（Ctrl+C）
trap cleanup_all SIGINT

# 1. 清理旧进程
echo -e "${GREEN}=== Cleaning up old processes ===${NC}"
cleanup_port $BACKEND_PORT
cleanup_port $FRONTEND_PORT
cleanup_port $MONITOR_PORT

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
langgraph dev --host 0.0.0.0 --port $BACKEND_PORT --no-browser --allow-blocking &
BACKEND_PID=$!
echo -e "Backend started with PID $BACKEND_PID (allow-blocking mode)"

# 等待后端启动
echo -e "${YELLOW}Waiting for backend to be ready...${NC}"
sleep 5

# 4. 启动监控面板
echo -e "${BLUE}=== Starting Monitor Dashboard ===${NC}"
python monitor_app_v2.py &
MONITOR_PID=$!
echo -e "Monitor started with PID $MONITOR_PID"

# 等待监控面板启动
sleep 3

# 5. 启动前端
echo -e "${GREEN}=== Starting Gradio Frontend ===${NC}"
python gradio_app.py &
FRONTEND_PID=$!
echo -e "Frontend started with PID $FRONTEND_PID"

# 等待所有服务稳定
sleep 2

# 获取本机局域网 IP
LOCAL_IP=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)

# 显示访问信息
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}✅ All services started successfully!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e ""
echo -e "${BLUE}🤖 AI Persona:${NC} ${PERSONA_NAME}"
echo -e ""
echo -e "${BLUE}🚀 LangGraph Backend:${NC}"
echo -e "   本地访问: http://127.0.0.1:${BACKEND_PORT}"
echo -e "   API Docs: http://127.0.0.1:${BACKEND_PORT}/docs"
echo -e "   局域网访问: http://${LOCAL_IP}:${BACKEND_PORT}"
echo -e ""
echo -e "${BLUE}🔍 Monitor Dashboard:${NC}"
echo -e "   本地访问: http://127.0.0.1:${MONITOR_PORT}"
echo -e "   局域网访问: http://${LOCAL_IP}:${MONITOR_PORT}"
echo -e "   （查看所有客户端的实时对话）"
echo -e ""
echo -e "${BLUE}💬 Gradio Frontend:${NC}"
echo -e "   本地访问: http://127.0.0.1:${FRONTEND_PORT}"
echo -e "   局域网访问: http://${LOCAL_IP}:${FRONTEND_PORT}"
echo -e "   （用于本地测试对话）"
echo -e ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"
echo -e ""

# 等待用户中断
wait

