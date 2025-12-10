#!/bin/bash

# 配置
PORT=2024
VENV_PATH="../.venv/bin/activate"

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Checking port $PORT...${NC}"

# 查找占用端口的进程 PID
PID=$(lsof -ti :$PORT)

if [ -n "$PID" ]; then
    echo -e "${YELLOW}Port $PORT is in use by PID $PID. Killing it...${NC}"
    kill -9 $PID
    echo -e "${GREEN}Process $PID killed.${NC}"
else
    echo -e "${GREEN}Port $PORT is free.${NC}"
fi

# 检查虚拟环境是否存在
if [ -f "$VENV_PATH" ]; then
    echo -e "${GREEN}Activating virtual environment...${NC}"
    source "$VENV_PATH"
else
    echo -e "${YELLOW}Warning: Virtual environment not found at $VENV_PATH${NC}"
fi

echo -e "${GREEN}Starting LangGraph dev server...${NC}"
# 启动 LangGraph
langgraph dev





