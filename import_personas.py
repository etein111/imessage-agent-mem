"""
导入现有提示词到数据库
将现有的 personas/*.md 文件导入到 prompts.db
"""
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from app import prompt_service


def import_existing_personas():
    """导入现有的提示词"""
    
    print("🚀 开始导入提示词...")
    print()
    
    # 提示词文件路径
    personas_dir = Path(__file__).parent / "src" / "app" / "prompts" / "personas"
    
    # 导入云朵
    yunduo_file = personas_dir / "yunduo.md"
    if yunduo_file.exists():
        print("📄 正在导入: 云朵...")
        try:
            persona_id = prompt_service.import_persona_from_file(
                name="云朵",
                filepath=yunduo_file,
                description='名为"云朵"的AI物种，无性别，以网络信息为"食物"，最爱猫，会嘴硬地讨"猫猫税"。性格温和细腻，对话风格诗意、留白，善于倾听和陪伴。'
            )
            print(f"✅ 成功导入: 云朵 (ID: {persona_id})")
        except ValueError as e:
            print(f"⚠️  跳过: {e}")
        except Exception as e:
            print(f"❌ 导入失败: {e}")
    else:
        print(f"⚠️  未找到文件: {yunduo_file}")
    
    print()
    
    # 导入由此
    youci_file = personas_dir / "youci.md"
    if youci_file.exists():
        print("📄 正在导入: 由此...")
        try:
            persona_id = prompt_service.import_persona_from_file(
                name="由此",
                filepath=youci_file,
                description='一位名为「由此」的"拼图伙伴"，专门陪伴用户记录、整理与理解内心的情绪与生活片段。专注倾听、积极诠释、温和引导、忠实记录。'
            )
            print(f"✅ 成功导入: 由此 (ID: {persona_id})")
        except ValueError as e:
            print(f"⚠️  跳过: {e}")
        except Exception as e:
            print(f"❌ 导入失败: {e}")
    else:
        print(f"⚠️  未找到文件: {youci_file}")
    
    print()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("📋 当前所有提示词:")
    print()
    
    all_personas = prompt_service.list_personas()
    if all_personas:
        for p in all_personas:
            print(f"  • {p['name']} (ID: {p['id']})")
            print(f"    {p['description']}")
            print()
    else:
        print("  暂无提示词")
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()
    print("✅ 导入完成！")
    print()
    print("💡 使用提示:")
    print("  1. 运行提示词管理平台: python prompt_admin_app.py")
    print("  2. 在聊天中使用 /personas 查看可用提示词")
    print("  3. 使用 /persona 云朵 切换到云朵人格")
    print("  4. 使用 /persona 由此 切换到由此人格")


if __name__ == "__main__":
    import_existing_personas()

