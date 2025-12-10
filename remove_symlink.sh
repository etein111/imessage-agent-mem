#!/bin/bash
# 删除软链接，改用 PYTHONPATH 方式

cd /Users/weitianyi/Desktop/xbuddy/langgraph/my_langgraph_app

echo "🗑️  删除软链接..."
if [ -L "app" ]; then
    rm app
    echo "✅ 软链接已删除"
else
    echo "ℹ️  软链接不存在"
fi

echo ""
echo "📝 现在需要设置 PYTHONPATH："
echo ""
echo "方式 1: 在 run_with_monitor.sh 开头添加："
echo "   export PYTHONPATH=\"/Users/weitianyi/Desktop/xbuddy/langgraph/my_langgraph_app/src:\$PYTHONPATH\""
echo ""
echo "方式 2: 在 ~/.bashrc 或 ~/.zshrc 添加："
echo "   export PYTHONPATH=\"/Users/weitianyi/Desktop/xbuddy/langgraph/my_langgraph_app/src:\$PYTHONPATH\""
echo ""
echo "⚠️  删除软链接后，需要设置 PYTHONPATH 才能正常导入！"

