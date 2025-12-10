# AI Agent (Cloud Buddy) API 接口文档

本文档描述了 AI 社交应用 "云朵 (Cloud Buddy)" 后端服务的 API 接口规范。
后端基于 LangGraph 框架构建，提供流式对话能力。

## 1. 服务信息

- **Base URL**: `http://localhost:2024` (本地开发) / `https://api.your-domain.com` (生产环境)
- **API 协议**: REST API + Server-Sent Events (SSE)
- **Graph ID (Assistant ID)**: `pipeline_chat_v6`

---

## 2. 核心接口：发起流式对话

前端通过此接口发送用户消息，并接收 AI 的流式回复及状态更新。

- **Endpoint**: `POST /threads/{thread_id}/runs/stream`
- **Content-Type**: `application/json`

### 2.1 请求参数 (Request)

| 参数名 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `thread_id` | string | 是 | 会话 ID (UUID)，由前端生成并维护，用于标识一次连续的对话上下文。 |
| `assistant_id` | string | 是 | 固定为 `pipeline_chat_v6`。 |
| `stream_mode` | list | 是 | 固定为 `["messages", "updates"]`，以同时获取回复内容和内部状态更新。 |
| `input` | object | 是 | 传递给 Agent 的初始状态数据。 |

#### Input 对象结构

```json
{
  "messages": [
    {
      "role": "user",
      "content": "用户发送的消息内容"
    }
  ],
  "user_id": "user_123456",       // 用户唯一标识，用于关联长期记忆
  "conversation_id": "conv_abc"   // (可选) 显式指定会话ID，通常与 thread_id 保持一致
}
```

### 2.2 响应数据 (Response - SSE Stream)

接口返回 Server-Sent Events (SSE) 流。前端需要监听不同类型的事件 (`event`)。

#### 事件类型 1: `messages` (流式回复)

**重要：LangGraph 返回的是累积后的完整内容，直接替换即可！**

AI 生成的文本内容是**流式返回**的，但每个 `messages` 事件包含的是**从开始到当前时刻的完整累积内容**，而不是增量片段。前端应该**直接替换**显示内容，而不是累加。

**为什么 LangGraph 使用这种方式？**

LangGraph 是基于**状态图（StateGraph）**的框架，它的流式输出机制设计为：
- 每次节点执行后，推送**完整状态快照**（而不是增量片段）
- 这样设计的好处是：简化状态管理、支持复杂的多节点图、避免前端需要维护累积逻辑
- 但确实不符合常规 SSE 的"增量片段"预期

**如果需要真正的 token-by-token 增量流式输出：**

如果前端确实需要增量片段（如 "你" → "你好" → "你好，" → "你好，我"），需要：
1. 后端节点使用 `model.astream()` 并通过 `writer` 推送增量 token
2. 前端监听 `custom` 事件而不是 `messages` 事件
3. 这需要修改后端节点代码和前端处理逻辑

**当前实现（推荐）：**
- 使用 `messages` 事件，每次收到完整累积内容后直接替换显示
- 虽然每次都是完整内容，但更新频率足够高（通常每 100-200ms），用户体验仍然流畅

**数据示例:**

第一个事件（累积到 "你好"）：
```json
event: messages
data: [
  {
    "content": "你好",
    ...
  },
  {
    "langgraph_node": "generate_reply",
    ...
  }
]
```

第二个事件（累积到 "你好，我是云朵"）：
```json
event: messages
data: [
  {
    "content": "你好，我是云朵",
    ...
  }
]
```

第三个事件（累积到完整回复）：
```json
event: messages
data: [
  {
    "content": "你好，我是云朵，很高兴认识你",
    ...
  }
]
```

**前端处理逻辑（关键）：**

```typescript
for await (const chunk of stream) {
  if (chunk.event === "messages") {
    const [message] = chunk.data;
    if (message.content) {
      // ✅ 正确：直接替换，因为 content 已经是累积后的完整内容
      updateChatUI(message.content);
    }
  }
}
```

**错误示例（会导致重复累加）：**
```typescript
// ❌ 错误：如果累加，会导致内容重复
let fullMessage = "";
for await (const chunk of stream) {
  if (chunk.event === "messages") {
    fullMessage += chunk.data[0].content; // 错误！content 已经是完整的，累加会重复
    updateChatUI(fullMessage);
  }
}
```

**正确做法：**
- 每次收到 `messages` 事件，直接使用 `message.content` 更新 UI（替换，不累加）。
- 每次新的对话轮次开始时，清空之前的显示内容。
- `messages/partial` 事件的处理方式与 `messages` 相同（也是完整内容）。

#### 事件类型 2: `updates` (状态更新)

AI 内部状态的变化，用于更新前端的“记忆看板”或“状态栏”。

**数据示例:**
```json
event: updates
data: {
  "estimate_state": {
    "current_emotion": "happy",
    "dialogue_type": "small_talk"
  },
  "plan_goal": {
    "current_goal": "cheer_up",
    "goal_instruction": "..."
  },
  "save_memory": {
    "short_term_memory": [
      "用户喜欢打乒乓球...",
      "用户今天心情不错..."
    ]
  },
  "call_tools": {
    "tool_results": {
        "get_weather": "北京今天晴朗..."
    }
  }
}
```

**前端处理逻辑:**
根据 `data` 对象中的 Key 判断是哪个节点的更新：

1.  **`estimate_state`**: 更新用户情绪 (`current_emotion`) 和对话类型 (`dialogue_type`)。
2.  **`plan_goal`**: 更新当前 AI 目标 (`current_goal`)。
3.  **`save_memory`**: 更新记忆列表 (`short_term_memory`)。
4.  **`call_tools`**: (可选) 展示工具调用结果 (`tool_results`)。

---

## 3. 字段值枚举 (Enum)

### 用户情绪 (`current_emotion`)
- `happy`, `sad`, `stressed`, `bored`, `neutral`, `angry`, `excited`, `curious`

### 对话类型 (`dialogue_type`)
- `small_talk` (闲聊)
- `support` (寻求安慰/情感支持)
- `task` (任务导向)
- `onboarding` (初次见面/破冰)
- `flirt` (调情/玩笑)
- `conflict` (冲突)

### AI 目标 (`current_goal`)
- `casual_chat` (默认闲聊)
- `cheer_up` (安抚/共情)
- `collect_profile` (收集用户信息)
- `deep_talk` (深化话题)
- `light_task` (简单任务)
- `report_weather` (播报天气)
- `report_time` (播报时间)
- `draw_topic_card` (抽取话题卡)
- `give_warm_quote` (赠送暖心金句)

---

## 4. 前端 SDK 调用示例 (JS/TS)

推荐使用 `@langchain/langgraph-sdk`。

```typescript
import { Client } from "@langchain/langgraph-sdk";

const client = new Client({ apiUrl: "http://localhost:2024" });

async function sendMessage(userMessage, threadId) {
  const stream = await client.runs.stream(
    threadId,
    "pipeline_chat_v6",
    {
      input: {
        messages: [{ role: "user", content: userMessage }],
        user_id: "current_user_id",
      },
      streamMode: ["messages", "updates"],
    }
  );

  for await (const chunk of stream) {
    if (chunk.event === "messages" || chunk.event === "messages/partial") {
      // 处理文本流：直接使用 content（已经是累积后的完整内容）
      const [message] = chunk.data;
      if (message.content) {
        // ✅ 直接替换，不累加
        updateChatUI(message.content);
      }
    } else if (chunk.event === "updates") {
      // 处理状态更新
      const update = chunk.data;
      
      if (update.estimate_state) {
        updateStatusUI(update.estimate_state);
      }
      if (update.plan_goal) {
        updateGoalUI(update.plan_goal.current_goal);
      }
      if (update.save_memory) {
        updateMemoryUI(update.save_memory.short_term_memory);
      }
    }
  }
}
```

**完整示例（React Hook）：**

```typescript
function useChatStream() {
  const [currentMessage, setCurrentMessage] = useState("");
  
  const sendMessage = async (userInput: string, threadId: string) => {
    setCurrentMessage(""); // 重置，准备接收新回复
    
    const stream = await client.runs.stream(threadId, "pipeline_chat_v6", {
      input: { messages: [{ role: "user", content: userInput }] },
      streamMode: ["messages", "updates"],
    });
    
    for await (const chunk of stream) {
      if (chunk.event === "messages" || chunk.event === "messages/partial") {
        const content = chunk.data[0]?.content || "";
        // ✅ 直接替换，因为 content 已经是累积后的完整内容
        setCurrentMessage(content);
      }
    }
  };
  
  return { currentMessage, sendMessage };
}
```

