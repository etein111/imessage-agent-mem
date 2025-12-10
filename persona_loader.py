"""
人设加载器 - 动态加载不同的AI人设配置
支持从 personas/ 目录加载 Markdown 格式的人设文件
"""

import os
from pathlib import Path
from typing import Optional

class PersonaLoader:
    """人设加载器类"""
    
    def __init__(self, personas_dir: str = "personas"):
        """
        初始化人设加载器
        
        Args:
            personas_dir: 人设配置文件目录，默认为 "personas"
        """
        self.personas_dir = Path(__file__).parent / personas_dir
        self.current_persona = None
        self.current_persona_name = None
    
    def list_available_personas(self) -> list:
        """
        列出所有可用的人设
        
        Returns:
            人设名称列表（不含.md后缀）
        """
        if not self.personas_dir.exists():
            return []
        
        personas = []
        for file in self.personas_dir.glob("*.md"):
            personas.append(file.stem)
        
        return sorted(personas)
    
    def load_persona(self, persona_name: str) -> str:
        """
        加载指定的人设
        
        Args:
            persona_name: 人设名称（不含.md后缀）
        
        Returns:
            人设的完整文本内容
        
        Raises:
            FileNotFoundError: 人设文件不存在时抛出
        """
        persona_file = self.personas_dir / f"{persona_name}.md"
        
        if not persona_file.exists():
            available = self.list_available_personas()
            raise FileNotFoundError(
                f"人设 '{persona_name}' 不存在。\n"
                f"可用的人设: {', '.join(available)}"
            )
        
        with open(persona_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        self.current_persona = content
        self.current_persona_name = persona_name
        
        return content
    
    def get_current_persona(self) -> Optional[str]:
        """
        获取当前加载的人设内容
        
        Returns:
            当前人设的文本内容，如果未加载则返回 None
        """
        return self.current_persona
    
    def get_current_persona_name(self) -> Optional[str]:
        """
        获取当前加载的人设名称
        
        Returns:
            当前人设的名称，如果未加载则返回 None
        """
        return self.current_persona_name


def load_persona_from_env(default: str = "yunduo") -> str:
    """
    从环境变量加载人设，如果未设置则使用默认值
    
    Args:
        default: 默认人设名称
    
    Returns:
        人设的完整文本内容
    
    Environment Variables:
        PERSONA_NAME: 要加载的人设名称
    """
    loader = PersonaLoader()
    persona_name = os.getenv("PERSONA_NAME", default)
    
    try:
        persona_content = loader.load_persona(persona_name)
        print(f"✅ 已加载人设: {persona_name}")
        return persona_content
    except FileNotFoundError as e:
        print(f"⚠️ {e}")
        print(f"⚠️ 使用默认人设: {default}")
        return loader.load_persona(default)


if __name__ == "__main__":
    # 测试代码
    loader = PersonaLoader()
    
    print("可用的人设:")
    for persona in loader.list_available_personas():
        print(f"  - {persona}")
    
    print("\n测试加载云朵人设:")
    yunduo = loader.load_persona("yunduo")
    print(f"内容长度: {len(yunduo)} 字符")
    print(f"前100字符: {yunduo[:100]}...")
    
    print("\n测试加载由此人设:")
    youci = loader.load_persona("youci")
    print(f"内容长度: {len(youci)} 字符")
    print(f"前100字符: {youci[:100]}...")


