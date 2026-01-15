"""
提示词管理平台 - Gradio Web UI
用于管理AI人格/提示词
"""
import gradio as gr
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from src.app import prompt_service


def list_personas_ui():
    """列出所有提示词"""
    personas = prompt_service.list_personas()
    
    if not personas:
        return "暂无提示词"
    
    # 格式化输出
    result = "## 提示词列表\n\n"
    for p in personas:
        result += f"### {p['name']} (ID: {p['id']})\n"
        result += f"**描述**: {p['description'] or '无'}\n"
        result += f"**创建时间**: {p['created_at']}\n"
        result += f"**更新时间**: {p['updated_at']}\n"
        result += f"**内容预览**: {p['content'][:200]}...\n\n"
        result += "---\n\n"
    
    return result


def view_persona_ui(persona_name):
    """查看提示词详情"""
    if not persona_name:
        return "请输入提示词名称", ""
    
    persona = prompt_service.get_persona_by_name(persona_name)
    
    if not persona:
        return f"未找到提示词: {persona_name}", ""
    
    info = f"""# {persona['name']}

**ID**: {persona['id']}
**描述**: {persona['description'] or '无'}
**创建时间**: {persona['created_at']}
**更新时间**: {persona['updated_at']}

---
"""
    
    content = persona['content']
    
    return info, content


def create_persona_ui(name, description, content):
    """创建新提示词"""
    if not name or not content:
        return "❌ 名称和内容不能为空", ""
    
    try:
        persona_id = prompt_service.create_persona(name, content, description or "")
        msg = f"✅ 成功创建提示词: {name} (ID: {persona_id})"
        personas_list = list_personas_ui()
        return msg, personas_list
    except ValueError as e:
        return f"❌ {str(e)}", ""
    except Exception as e:
        return f"❌ 创建失败: {str(e)}", ""


def update_persona_ui(persona_name, new_name, new_description, new_content):
    """更新提示词"""
    if not persona_name:
        return "❌ 请输入要更新的提示词名称"
    
    persona = prompt_service.get_persona_by_name(persona_name)
    if not persona:
        return f"❌ 未找到提示词: {persona_name}"
    
    persona_id = persona['id']
    
    # 只更新非空字段
    kwargs = {}
    if new_name:
        kwargs['name'] = new_name
    if new_description:
        kwargs['description'] = new_description
    if new_content:
        kwargs['content'] = new_content
    
    if not kwargs:
        return "❌ 没有要更新的内容"
    
    try:
        success = prompt_service.update_persona(persona_id, **kwargs)
        if success:
            return f"✅ 成功更新提示词: {persona_name}"
        else:
            return "❌ 更新失败"
    except ValueError as e:
        return f"❌ {str(e)}"
    except Exception as e:
        return f"❌ 更新失败: {str(e)}"


def delete_persona_ui(persona_name, confirm_text):
    """删除提示词"""
    if not persona_name:
        return "❌ 请输入要删除的提示词名称", ""
    
    if confirm_text != persona_name:
        return f"❌ 请输入 '{persona_name}' 以确认删除", ""
    
    persona = prompt_service.get_persona_by_name(persona_name)
    if not persona:
        return f"❌ 未找到提示词: {persona_name}", ""
    
    persona_id = persona['id']
    success = prompt_service.delete_persona(persona_id)
    
    if success:
        personas_list = list_personas_ui()
        return f"✅ 成功删除提示词: {persona_name}", personas_list
    else:
        return "❌ 删除失败", ""


def import_from_file_ui(name, description, file):
    """从文件导入提示词"""
    if not name or not file:
        return "❌ 名称和文件不能为空", ""
    
    try:
        # 读取文件内容
        content = file.decode('utf-8')
        
        # 创建提示词
        persona_id = prompt_service.create_persona(name, content, description or "")
        
        msg = f"✅ 成功从文件导入提示词: {name} (ID: {persona_id})"
        personas_list = list_personas_ui()
        return msg, personas_list
    except ValueError as e:
        return f"❌ {str(e)}", ""
    except Exception as e:
        return f"❌ 导入失败: {str(e)}", ""


# 构建UI
with gr.Blocks(title="提示词管理平台", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
    # 🎭 提示词管理平台
    
    管理AI人格/提示词，支持创建、查看、编辑、删除和导入。
    """)
    
    with gr.Tabs():
        # Tab 1: 查看所有提示词
        with gr.Tab("📋 查看提示词"):
            gr.Markdown("## 所有提示词")
            refresh_btn = gr.Button("🔄 刷新列表", variant="primary")
            personas_display = gr.Markdown(list_personas_ui())
            
            refresh_btn.click(
                fn=list_personas_ui,
                outputs=personas_display
            )
        
        # Tab 2: 查看单个提示词详情
        with gr.Tab("🔍 查看详情"):
            gr.Markdown("## 查看提示词详情")
            
            view_name_input = gr.Textbox(
                label="提示词名称",
                placeholder="例如: 云朵, 由此"
            )
            view_btn = gr.Button("查看", variant="primary")
            
            with gr.Row():
                with gr.Column(scale=1):
                    view_info_display = gr.Markdown("选择一个提示词查看详情")
                with gr.Column(scale=2):
                    view_content_display = gr.TextArea(
                        label="提示词内容",
                        lines=20,
                        interactive=False
                    )
            
            view_btn.click(
                fn=view_persona_ui,
                inputs=view_name_input,
                outputs=[view_info_display, view_content_display]
            )
        
        # Tab 3: 创建新提示词
        with gr.Tab("➕ 创建提示词"):
            gr.Markdown("## 创建新提示词")
            
            create_name_input = gr.Textbox(
                label="名称*",
                placeholder="例如: 小助手"
            )
            create_desc_input = gr.Textbox(
                label="描述",
                placeholder="简要描述这个提示词的特点"
            )
            create_content_input = gr.TextArea(
                label="提示词内容*",
                lines=15,
                placeholder="输入完整的提示词内容..."
            )
            
            create_btn = gr.Button("✅ 创建", variant="primary")
            create_result = gr.Markdown()
            create_list_display = gr.Markdown()
            
            create_btn.click(
                fn=create_persona_ui,
                inputs=[create_name_input, create_desc_input, create_content_input],
                outputs=[create_result, create_list_display]
            )
        
        # Tab 4: 编辑提示词
        with gr.Tab("✏️ 编辑提示词"):
            gr.Markdown("## 编辑提示词")
            gr.Markdown("**注意**: 只有填写的字段会被更新")
            
            update_old_name_input = gr.Textbox(
                label="当前提示词名称*",
                placeholder="要编辑的提示词名称"
            )
            
            update_new_name_input = gr.Textbox(
                label="新名称（可选）",
                placeholder="留空则不修改"
            )
            update_new_desc_input = gr.Textbox(
                label="新描述（可选）",
                placeholder="留空则不修改"
            )
            update_new_content_input = gr.TextArea(
                label="新内容（可选）",
                lines=15,
                placeholder="留空则不修改"
            )
            
            update_btn = gr.Button("💾 更新", variant="primary")
            update_result = gr.Markdown()
            
            update_btn.click(
                fn=update_persona_ui,
                inputs=[
                    update_old_name_input,
                    update_new_name_input,
                    update_new_desc_input,
                    update_new_content_input
                ],
                outputs=update_result
            )
        
        # Tab 5: 删除提示词
        with gr.Tab("🗑️ 删除提示词"):
            gr.Markdown("## 删除提示词")
            gr.Markdown("**警告**: 此操作不可撤销！")
            
            delete_name_input = gr.Textbox(
                label="提示词名称",
                placeholder="要删除的提示词名称"
            )
            delete_confirm_input = gr.Textbox(
                label="确认删除",
                placeholder="重新输入提示词名称以确认"
            )
            
            delete_btn = gr.Button("🗑️ 删除", variant="stop")
            delete_result = gr.Markdown()
            delete_list_display = gr.Markdown()
            
            delete_btn.click(
                fn=delete_persona_ui,
                inputs=[delete_name_input, delete_confirm_input],
                outputs=[delete_result, delete_list_display]
            )
        
        # Tab 6: 从文件导入
        with gr.Tab("📥 导入提示词"):
            gr.Markdown("## 从文件导入提示词")
            gr.Markdown("支持导入 `.txt` 或 `.md` 文件")
            
            import_name_input = gr.Textbox(
                label="名称*",
                placeholder="例如: 导入的提示词"
            )
            import_desc_input = gr.Textbox(
                label="描述",
                placeholder="简要描述"
            )
            import_file_input = gr.File(
                label="选择文件*",
                file_types=[".txt", ".md"],
                type="binary"
            )
            
            import_btn = gr.Button("📥 导入", variant="primary")
            import_result = gr.Markdown()
            import_list_display = gr.Markdown()
            
            import_btn.click(
                fn=import_from_file_ui,
                inputs=[import_name_input, import_desc_input, import_file_input],
                outputs=[import_result, import_list_display]
            )
    
    gr.Markdown("""
    ---
    
    ### 使用说明
    
    - **查看提示词**: 查看所有已创建的提示词列表
    - **查看详情**: 查看单个提示词的完整内容
    - **创建提示词**: 手动创建新的提示词
    - **编辑提示词**: 修改现有提示词的名称、描述或内容
    - **删除提示词**: 删除不需要的提示词（需要确认）
    - **导入提示词**: 从 .txt 或 .md 文件导入提示词
    
    创建或导入提示词后，用户可以在聊天中使用 `/persona 提示词名称` 切换人格。
    """)


if __name__ == "__main__":
    demo.launch(
        server_name="127.0.0.1",
        server_port=7861,
        share=False
    )

