# 为什么 LangGraph 的 messages 事件是"累加"的？

## 核心问题

你观察到的现象：
- 第 1 次收到：`"你好"`
- 第 2 次收到：`"你好，我是云朵"`
- 第 3 次收到：`"你好，我是云朵，很高兴认识你"`

每次都是**累积后的完整内容**，而不是增量片段（如 `"你"` → `"好"` → `"，"` → `"我"`）。

## 原因分析

### 1. 我们的代码做了什么？

```python
# simple_chat.py
model = ChatVertexAI(
    streaming=True,  # ✅ 启用了流式输出
    ...
)

# 在节点中
response = await model.ainvoke(normalized_messages, config=config)
return {"messages": [response]}
```

**关键点：**
- ✅ 我们设置了 `streaming=True`（LLM 支持流式生成）
- ❌ 但我们使用的是 `model.ainvoke()`，而不是 `model.astream()`
- ✅ 我们依赖 LangGraph 的**自动流式捕获机制**

### 2. LangGraph 的流式捕获机制

当 LLM 内部流式生成时，LangGraph 会通过 **callback 机制**自动捕获更新：

```
LLM 流式生成过程：
Token 1: "你"     → LangGraph callback 触发 → 推送完整状态: "你"
Token 2: "好"     → LangGraph callback 触发 → 推送完整状态: "你好"
Token 3: "，"     → LangGraph callback 触发 → 推送完整状态: "你好，"
Token 4: "我"     → LangGraph callback 触发 → 推送完整状态: "你好，我"
...
```

**关键理解：**
- LangGraph 捕获的是**状态快照**（State Snapshot），不是**增量更新**（Delta Update）
- 每次 callback 触发时，LangGraph 会：
  1. 获取当前完整的 `state.messages`（包括累积后的完整 AI 回复）
  2. 通过 SSE 推送这个**完整的状态快照**

### 3. 为什么 LangGraph 这样设计？

**设计理念：基于状态图（StateGraph）**

LangGraph 的核心是**状态图**，它的流式输出机制遵循以下原则：

1. **状态一致性**：每次推送都是完整状态，确保前端和后端状态一致
2. **简化前端逻辑**：前端不需要维护累积变量，直接替换即可
3. **支持复杂图结构**：在多节点、条件路由的场景下，完整状态快照更容易处理

**类比：**
- **增量方式**（传统 SSE）：`"你"` → `"好"` → `"，"` → `"我"`（前端需要累加）
- **快照方式**（LangGraph）：`"你"` → `"你好"` → `"你好，"` → `"你好，我"`（前端直接替换）

### 4. 底层实现细节

当 LLM 流式生成时：

```python
# LangGraph 内部（简化版）
async def node_execution():
    # LLM 开始流式生成
    async for token in model.astream_internal():
        # 每次收到新 token，累积到完整消息
        accumulated_message += token
        
        # LangGraph 通过 callback 捕获这个更新
        # 但推送的是完整状态，不是单个 token
        yield {
            "event": "messages",
            "data": [{
                "content": accumulated_message  # ← 完整累积内容
            }]
        }
```

**关键点：**
- LLM 内部确实是 token-by-token 流式生成的
- 但 LangGraph 在捕获时，会获取**累积后的完整内容**
- 然后推送这个完整内容作为状态快照

## 总结

**"累加"不是 bug，而是 LangGraph 的设计选择：**

1. ✅ **LLM 层面**：确实是流式生成（token by token）
2. ✅ **LangGraph 层面**：捕获流式更新，但推送完整状态快照
3. ✅ **前端层面**：收到的是累积后的完整内容，直接替换显示

**优势：**
- 前端逻辑简单（不需要累加）
- 状态一致性保证
- 支持复杂图结构

**劣势：**
- 不符合传统 SSE 的"增量片段"预期
- 每次传输的数据量略大（但更新频率高，影响不大）

## 如果需要真正的增量流式输出

如果确实需要 token-by-token 的增量片段（如 `"你"` → `"好"` → `"，"`），需要：

1. **后端修改**：使用 `model.astream()` + `writer` 手动推送每个 token
2. **前端修改**：监听 `custom` 事件而不是 `messages` 事件
3. **复杂度**：需要修改多个节点和前端处理逻辑

**当前实现的体验：**
- 虽然每次都是完整内容，但更新频率足够高（通常每 100-200ms）
- 用户体验仍然流畅（文字逐字出现的效果）
- 架构更简单，维护成本更低




