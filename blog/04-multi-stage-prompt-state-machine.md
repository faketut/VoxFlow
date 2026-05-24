# 多阶段 AI 对话设计：用 System Prompt 实现对话状态机

> **TL;DR**：与其在代码里硬编码对话流程，不如把每个阶段的规则写进 system prompt，用工具调用作为状态转换触发器。这让 AI 本身成为状态机的执行引擎。

---

## 为什么需要多阶段对话？

一个完整的客服电话不是一次问答，而是有结构的流程：

```
来电
  → 阶段1：身份验证（你是谁？）
  → 阶段2：主要问题处理（你需要什么？）
  → 阶段3：总结收尾（我们达成了什么？）
  → 挂断
```

如果用一个巨大的 system prompt 描述全部三个阶段，AI 很可能跳步骤、忘记验证、或者在阶段1就直接回答业务问题。

解决方案：**每个阶段用一个单独的 system prompt，通过工具调用切换。**

---

## 架构：Prompt 即状态

```
┌─────────────────────────────────────────────────────┐
│                   Ultravox 会话                      │
│                                                     │
│   SystemPrompt = STAGE_1_PROMPT                     │
│         │                                           │
│         │ AI 调用 move_to_main_convo()               │
│         ▼                                           │
│   SystemPrompt = STAGE_2_PROMPT  ← 新建 Ultravox 会话 │
│         │                                           │
│         │ AI 调用 move_to_call_summary()             │
│         ▼                                           │
│   SystemPrompt = STAGE_3_PROMPT  ← 再新建一个会话    │
│         │                                           │
│         │ AI 调用 hangUp()                          │
│         ▼                                           │
│      通话结束                                        │
└─────────────────────────────────────────────────────┘
```

关键洞察：**Ultravox 的 system prompt 是创建会话时就固定的**，要换阶段就必须创建新会话。这意味着"状态转换"在工程上是"断开旧 Ultravox 连接，用新 prompt 创建新连接"。

---

## Prompt 设计原则

### 1. 明确禁止跳步骤

```markdown
## Call Stage Transitions - STRICT GUIDELINES

1. **Proceed to MainConvo:**
   - ONLY proceed to this stage AFTER successful identity verification
   - NEVER proceed to MainConvo if verification failed or was not attempted
   - Do not move to MainConvo unless the customer has indicated they need help
     with clinic Q&A, schedule meeting, billing questions, or dental emergency.
```

用 `NEVER`、`ONLY`、`STRICT` 等强调词，而不是"请尽量"。LLM 在边界条件上容易走捷径，明确的禁令比模糊的期望有效得多。

### 2. 每个阶段只注册该阶段需要的工具

阶段1（身份验证）只需要：`verify`、`queryCorpus`、`move_to_main_convo`、`hangUp`
阶段2（主对话）只需要：`queryCorpus`、`schedule_meeting`、`move_to_call_summary`、`hangUp`

不在 prompt 里提、不在 `selectedTools` 里注册。工具越少，AI 越不容易误调用。

### 3. 时间戳注入

```python
def get_system_prompt() -> str:
    now = datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')
    return _SYSTEM_MESSAGE_TEMPLATE.format(
        now=now,
        agent_name=AGENT_NAME,
        company_name=COMPANY_NAME,
    )
```

在 prompt 末尾加当前时间，让 AI 知道"现在是几点"，避免回答预约相关问题时出错。

**常见坑**：用 f-string 在模块导入时就计算时间：

```python
# ❌ 错误：时间在服务启动时就冻结了
now = datetime.now(UTC).strftime(...)
SYSTEM_PROMPT = f"Current time: {now}"  # 永远是启动时间

# ✅ 正确：每次通话创建时重新计算
def get_system_prompt() -> str:
    now = datetime.now(UTC).strftime(...)
    return TEMPLATE.format(now=now)
```

---

## 工具调用触发状态转换

当 AI 决定进入下一阶段，它调用 `move_to_main_convo` 工具，携带当前上下文：

```python
# AI 发来的 tool invocation 消息
{
    "type": "client_tool_invocation",
    "toolName": "move_to_main_convo",
    "invocationId": "inv_123",
    "parameters": {
        "issue_type": "schedule_meeting",
        "issue_details": "Patient wants to book a checkup for next week",
        "customer_name": "Jane Doe"
    }
}
```

我们的 handler：

```python
async def handle_move_to_main_convo(uv_ws, invocation_id, params):
    # 1. 构建新阶段的 prompt（带上本阶段收集到的信息）
    new_prompt = get_stage_prompt(
        "main_convo",
        issue_context=params.issue_details,
    )

    # 2. 创建新的 Ultravox 会话
    join_url = await create_ultravox_call(
        system_prompt=new_prompt,
        first_message=f"I understand you need help with {params.issue_details}.",
    )

    # 3. 更新 session，通知 WebSocket 层切换连接
    session = await session_manager.get(call_sid)
    session["uvJoinUrl"] = join_url
    session["stage"] = "main_convo"

    # 4. 告知 Ultravox 工具执行完毕（它会收到结果后继续对话）
    await _send_tool_result(uv_ws, invocation_id, "Transferring now...")
```

---

## 上下文传递

状态转换时，关键信息需要从旧阶段传递到新阶段。有两种方式：

**方式1：新 prompt 里直接嵌入**
```python
new_prompt = MAINCONVO_TEMPLATE.format(
    verified_name=params.customer_name,
    issue_type=params.issue_type,
)
```

**方式2：通过 initialMessages 传递历史**
```python
payload = {
    "systemPrompt": new_prompt,
    "initialMessages": [
        {"role": "MESSAGE_ROLE_AGENT", "text": f"I've verified {params.customer_name}."},
        {"role": "MESSAGE_ROLE_USER", "text": params.issue_details},
    ],
}
```

方式2 更接近真实对话延续，但 token 消耗更多。对于电话场景，方式1 足够。

---

## 总结

| 设计决策 | 理由 |
|----------|------|
| 每阶段独立 prompt | 减少 AI 的"自由发挥"空间，强制遵守阶段规则 |
| 工具调用触发状态转换 | AI 主动决定何时转换，而不是代码轮询 |
| 每阶段最小工具集 | 减少误调用，降低 prompt 复杂度 |
| 运行时注入时间/身份 | 避免 prompt 冻结，支持白标换客户 |

本质上，这是用 **LLM 作为决策引擎**，用 **工具调用作为副作用接口**，用 **system prompt 作为行为约束**。三者组合起来，就是一个可以处理复杂业务流程的有限状态机。
