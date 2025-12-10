#!/bin/bash
# 修复重构后的导入路径问题

cd /Users/weitianyi/Desktop/xbuddy/langgraph/my_langgraph_app

echo "🔧 修复导入路径..."

# 方案: 在项目根目录创建软链接
if [ ! -L "app" ]; then
    ln -sf src/app app
    echo "✅ 创建 app -> src/app 软链接"
else
    echo "ℹ️  软链接已存在"
fi

# 设置PYTHONPATH
export PYTHONPATH="/Users/weitianyi/Desktop/xbuddy/langgraph/my_langgraph_app/src:$PYTHONPATH"
echo "✅ 已设置 PYTHONPATH"

echo ""
echo "📝 测试导入..."

# 激活虚拟环境并测试
echo "🔌 激活虚拟环境..."
if [ -f "../.venv/bin/activate" ]; then
    source ../.venv/bin/activate
    echo "✅ 虚拟环境已激活: ../.venv"
elif [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    echo "✅ 虚拟环境已激活: .venv"
else
    echo "⚠️  未找到虚拟环境，将使用系统 Python"
fi

cd src 2>/dev/null || true

python3 << PYTHON
import sys
sys.path.insert(0, '/Users/weitianyi/Desktop/xbuddy/langgraph/my_langgraph_app/src')

try:
    from app.graph.state import PipelineState
    print("✅ 状态定义导入成功")
except Exception as e:
    print(f"❌ 状态定义导入失败: {e}")

try:
    from app.config import get_system_prompt
    print("✅ 配置模块导入成功")
except Exception as e:
    print(f"❌ 配置模块导入失败: {e}")

try:
    from app.graph.nodes import load_context_node
    print("✅ 节点模块导入成功")
except Exception as e:
    print(f"❌ 节点模块导入失败: {e}")
PYTHON

echo ""
echo "🎉 导入路径修复完成！"
echo ""
echo "💡 提示: 如需永久生效，请将以下内容添加到启动脚本:"
echo '   export PYTHONPATH="/Users/weitianyi/Desktop/xbuddy/langgraph/my_langgraph_app/src:$PYTHONPATH"'

