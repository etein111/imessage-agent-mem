from typing import Any, Dict, List, Optional, Sequence
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../"))
libs_path = os.path.join(project_root, "Libs")

if libs_path not in sys.path:
    sys.path.insert(0, libs_path)
from mem0.memory.main import AsyncMemory
from src.app.config import MEM0_CONFIG

class AsyncMem0Adapter:
    def __init__(self, memory: AsyncMemory):
        self.memory = memory

    async def add_messages(
        self,
        messages: Sequence[Any],
        *,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        infer: bool = True,
    ):
        mem0_messages = self._convert_messages(messages)
        if not mem0_messages:
            return None

        return await self.memory.add(
            mem0_messages,
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            metadata=metadata,
            infer=infer,
        )


    async def search(
        self,
        query: str,
        *,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        limit: int = 5,
        threshold: Optional[float] = None,
        rerank: bool = True,
    ):
        res = await self.memory.search(
            query,
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            limit=limit,
            threshold=threshold,
            rerank=rerank,
        )
        return res


    def _convert_messages(self, messages: Sequence[Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for m in messages:
            if isinstance(m, dict):
                role = m.get("role")
                content = m.get("content")
                if role and content:
                    out.append({"role": role, "content": str(content)})
                continue

            cls = m.__class__.__name__
            if cls == "SystemMessage":
                role = "system"
            elif cls == "HumanMessage":
                role = "user"
            elif cls == "AIMessage":
                role = "assistant"
            elif cls == "ToolMessage":
                role = "assistant"
            else:
                role = getattr(m, "role", None) or getattr(m, "type", "user")

            content = getattr(m, "content", "")
            if content is None:
                continue
            if isinstance(content, list):
                content = "\n".join(str(x) for x in content if x is not None)

            content = str(content).strip()
            if not content:
                continue

            msg = {"role": role, "content": content}
            name = getattr(m, "name", None)
            if name:
                msg["name"] = name
            out.append(msg)
        return out

# 工厂函数：只在入口调用一次
async def build_mem0_adapter() -> AsyncMem0Adapter:
    mem0 = await AsyncMemory.from_config(MEM0_CONFIG)
    return AsyncMem0Adapter(mem0)
