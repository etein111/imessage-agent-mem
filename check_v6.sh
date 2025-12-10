#!/bin/bash
# V6 后端代码完整性检查脚本

echo "🔍 检查 Pipeline Chat V6 后端文件..."
echo "═══════════════════════════════════════════════════════════"
echo ""

missing=0
total=0

check_file() {
    total=$((total + 1))
    if [ -f "$1" ]; then
        echo "✅ $1"
    else
        echo "❌ $1 (缺失)"
        missing=$((missing + 1))
    fi
}

echo "📦 核心后端脚本 (8个):"
echo "───────────────────────────────────────────────────────────"
check_file "pipeline_chat_v6.py"
check_file "simple_chat.py"
check_file "memory_store.py"
check_file "memory_chat.py"
check_file "pipeline_chat.py"
check_file "pipeline_chat_v3.py"
check_file "pipeline_chat_v4.py"
check_file "tools.py"
echo ""

echo "🔧 配置文件 (2个):"
echo "───────────────────────────────────────────────────────────"
check_file "persona_loader.py"
check_file "langgraph.json"
echo ""

echo "🎭 人设文件 (2个):"
echo "───────────────────────────────────────────────────────────"
check_file "personas/yunduo.md"
check_file "personas/youci.md"
echo ""

echo "💾 数据文件 (运行时生成):"
echo "───────────────────────────────────────────────────────────"
if [ -f "memory_store.json" ]; then
    echo "✅ memory_store.json (已生成)"
else
    echo "⚠️  memory_store.json (未生成，首次运行时自动创建)"
fi
echo ""

echo "═══════════════════════════════════════════════════════════"
echo "总计: $total 个必需文件"
if [ $missing -eq 0 ]; then
    echo "✅ 所有文件完整，V6 后端就绪！"
else
    echo "❌ 缺失 $missing 个文件，请检查"
fi
echo "═══════════════════════════════════════════════════════════"
