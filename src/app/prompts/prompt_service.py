"""
提示词管理服务
管理AI人格/提示词的CRUD操作
"""
import sqlite3
from typing import List, Optional, Dict
from pathlib import Path

from app.config import BASE_DIR


# 数据库文件路径
DB_FILE = BASE_DIR / "prompts.db"


class PromptService:
    """提示词管理服务"""
    
    def __init__(self):
        """初始化数据库连接和表结构"""
        self.db_file = DB_FILE
        self._init_database()
    
    def _init_database(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        # 创建 personas 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS personas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 创建 user_personas 关联表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_personas (
                user_id TEXT NOT NULL,
                persona_id INTEGER NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (persona_id) REFERENCES personas (id),
                PRIMARY KEY (user_id, persona_id)
            )
        """)
        
        conn.commit()
        conn.close()
    
    def create_persona(self, name: str, content: str, description: str = "") -> int:
        """
        创建新的提示词
        
        Args:
            name: 提示词名称（唯一）
            content: 提示词内容
            description: 描述
        
        Returns:
            新创建的提示词ID
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "INSERT INTO personas (name, content, description) VALUES (?, ?, ?)",
                (name, content, description)
            )
            persona_id = cursor.lastrowid
            conn.commit()
            return persona_id
        except sqlite3.IntegrityError:
            raise ValueError(f"提示词名称 '{name}' 已存在")
        finally:
            conn.close()
    
    def get_persona_by_id(self, persona_id: int) -> Optional[Dict]:
        """
        根据ID获取提示词
        
        Args:
            persona_id: 提示词ID
        
        Returns:
            提示词字典或None
        """
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM personas WHERE id = ?", (persona_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def get_persona_by_name(self, name: str) -> Optional[Dict]:
        """
        根据名称获取提示词
        
        Args:
            name: 提示词名称
        
        Returns:
            提示词字典或None
        """
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM personas WHERE name = ?", (name,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def list_personas(self) -> List[Dict]:
        """
        获取所有提示词列表
        
        Returns:
            提示词列表
        """
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM personas ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def update_persona(self, persona_id: int, name: str = None, 
                      content: str = None, description: str = None) -> bool:
        """
        更新提示词
        
        Args:
            persona_id: 提示词ID
            name: 新名称（可选）
            content: 新内容（可选）
            description: 新描述（可选）
        
        Returns:
            是否更新成功
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        
        if not updates:
            conn.close()
            return False
        
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(persona_id)
        
        query = f"UPDATE personas SET {', '.join(updates)} WHERE id = ?"
        
        try:
            cursor.execute(query, params)
            conn.commit()
            success = cursor.rowcount > 0
        except sqlite3.IntegrityError:
            raise ValueError(f"提示词名称 '{name}' 已存在")
        finally:
            conn.close()
        
        return success
    
    def delete_persona(self, persona_id: int) -> bool:
        """
        删除提示词
        
        Args:
            persona_id: 提示词ID
        
        Returns:
            是否删除成功
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        # 先删除关联关系
        cursor.execute("DELETE FROM user_personas WHERE persona_id = ?", (persona_id,))
        # 再删除提示词
        cursor.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
        
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        
        return success
    
    def set_user_persona(self, user_id: str, persona_id: int) -> bool:
        """
        为用户设置提示词（会将该用户其他提示词设为非激活）
        
        Args:
            user_id: 用户ID
            persona_id: 提示词ID
        
        Returns:
            是否设置成功
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        # 1. 将该用户所有提示词设为非激活
        cursor.execute(
            "UPDATE user_personas SET is_active = 0 WHERE user_id = ?",
            (user_id,)
        )
        
        # 2. 设置当前提示词为激活
        cursor.execute(
            """
            INSERT INTO user_personas (user_id, persona_id, is_active)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, persona_id) 
            DO UPDATE SET is_active = 1
            """,
            (user_id, persona_id)
        )
        
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        
        return success
    
    def get_user_active_persona(self, user_id: str) -> Optional[Dict]:
        """
        获取用户当前激活的提示词
        
        Args:
            user_id: 用户ID
        
        Returns:
            提示词字典或None
        """
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT p.* FROM personas p
            JOIN user_personas up ON p.id = up.persona_id
            WHERE up.user_id = ? AND up.is_active = 1
            LIMIT 1
            """,
            (user_id,)
        )
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def get_user_personas(self, user_id: str) -> List[Dict]:
        """
        获取用户的所有提示词（包括激活状态）
        
        Args:
            user_id: 用户ID
        
        Returns:
            提示词列表（包含is_active字段）
        """
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT p.*, up.is_active FROM personas p
            JOIN user_personas up ON p.id = up.persona_id
            WHERE up.user_id = ?
            ORDER BY up.created_at DESC
            """,
            (user_id,)
        )
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def import_persona_from_file(self, name: str, filepath: Path, 
                                 description: str = "") -> int:
        """
        从文件导入提示词
        
        Args:
            name: 提示词名称
            filepath: 文件路径
            description: 描述
        
        Returns:
            新创建的提示词ID
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return self.create_persona(name, content, description)


# 全局实例
prompt_service = PromptService()

