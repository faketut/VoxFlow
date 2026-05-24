# 用 n8n 把 AI 电话系统接入任意工作流

> **TL;DR**：VoxFlow 是纯粹的 AI 通话中间件，不做任何业务持久化。所有业务逻辑（CRM 写入、日历预约、邮件通知）都通过 n8n webhook 外包出去。这让系统真正解耦，换业务不改代码。

---

## 设计思路：AI 只管对话，n8n 管业务

很多 AI 电话项目的常见问题：把 CRM 调用、日历 API、邮件发送全部写死在代码里。每换一个客户就要改代码、加环境变量、重新部署。

VoxFlow 的做法是：**所有业务逻辑都在 n8n 里**，代码只负责打电话。

```
VoxFlow (AI 通话层)          n8n (业务逻辑层)
─────────────────            ──────────────────
接电话                        查询 CRM，返回个性化问候
AI 对话                  →   触发预约流程
挂断，发摘要             →   写入 CRM，发确认邮件
```

---

## 三种 webhook 调用

整个系统只有一个 webhook 地址（`N8N_WEBHOOK_URL`），用 `route` 字段区分用途：

### Route "1"：通话开始，获取个性化首句话

```python
# 来电时调用
payload = {
    "route": "1",
    "number": "+14165550100",  # 来电号码
    "data": "empty",
}
# n8n 返回：
# { "firstMessage": "Hi John, welcome back to Downtown Dental!" }
```

n8n 收到后，可以根据来电号码查 CRM：
```
Webhook → 查找联系人（HubSpot / Salesforce）
        → 如果是老客户：返回个性化问候
        → 如果是新号码：返回通用问候
```

VoxFlow 端有完整的 fallback 逻辑：

```python
async def _fetch_first_message_from_n8n(caller_number: str) -> str:
    if not N8N_WEBHOOK_URL:
        return DEFAULT_FIRST_MESSAGE  # fallback 1: URL 未配置

    try:
        resp = await client.post(N8N_WEBHOOK_URL, json=payload)
    except (httpx.TimeoutException, httpx.HTTPError):
        return DEFAULT_FIRST_MESSAGE  # fallback 2: 网络错误

    if resp.status_code >= 400:
        return DEFAULT_FIRST_MESSAGE  # fallback 3: n8n 报错

    data = json.loads(resp.text)
    return data.get("firstMessage") or DEFAULT_FIRST_MESSAGE  # fallback 4: 字段缺失
```

四层 fallback 保证：**n8n 挂掉不影响接电话**。

---

### Route "2"：通话结束，上传完整摘要

```python
# 挂断后调用
payload = {
    "route": "2",
    "number": "+14165550100",
    "data": "Agent: Thank you for calling...\nUser: I need to reschedule...\n...",
}
```

`data` 是完整的对话文字记录（transcript）。n8n 收到后可以：

```
Webhook → 用 AI 总结摘要（OpenAI/Claude）
        → 写入 CRM 联系人备注
        → 发送邮件给诊所经理
        → 存入数据库
        → 触发后续随访流程
```

这是 VoxFlow 向外界输出的**唯一持久化数据**。代码本身不存数据库。

---

### Route "3"：AI 触发预约工具

这个 route 比较特殊：它是由 **Ultravox 直接调用**（不经过 VoxFlow Python 代码），在工具定义里配置：

```python
{
    "temporaryTool": {
        "modelToolName": "schedule_meeting",
        "description": "Send an online booking link to the patient via email or text.",
        "http": {
            "baseUrlPattern": N8N_WEBHOOK_URL,  # 直接 POST 到 n8n
            "httpMethod": "POST",
        },
    }
}
```

AI 决定预约时，Ultravox 平台直接 POST 到 n8n：

```json
{
    "route": 3,
    "pt_Name": "Jane Doe",
    "pt_email": "jane@example.com",
    "pt_phoneNumber": "4165550100",
    "bookinglink": "https://booking.example.com/slot/123",
    "clinicName": "Downtown Dental"
}
```

n8n 处理后返回：
```json
{ "message": "Booking link has been sent to jane@example.com." }
```

这条 message 会被 Ultravox 直接读给用户听。

---

## 在 n8n 里搭建 Webhook 节点

最小可用的 n8n 工作流：

```
[Webhook]
    |
[Switch: 按 route 分支]
    |         |         |
  route=1   route=2   route=3
    |         |         |
查 CRM     写摘要    发预约邮件
    |         |         |
返回        返回       返回
firstMessage  200     { message }
```

关键配置：
- **Method**: POST
- **Response Mode**: Using 'Respond to Webhook' node（同步返回，VoxFlow 在等）
- **Content-Type**: application/json

---

## 超时处理

VoxFlow 使用 `HTTP_TIMEOUT_SECONDS`（默认 10 秒）等待 n8n 响应。如果 n8n 的 route "1" 超过 10 秒，用户已经在电话里等太久了。建议：

| Route | n8n 处理时间目标 |
|-------|----------------|
| 1 (首句话) | < 2 秒（用户在等） |
| 2 (摘要) | < 10 秒（用户已挂断，异步也行） |
| 3 (预约) | < 5 秒（用户在等确认） |

Route "2" 实际上可以让 n8n 立刻返回 200，然后异步处理。VoxFlow 只关心 HTTP 状态码，不解析 route "2" 的响应体。

---

## 总结

这种架构的核心价值是**关注点分离**：

- **VoxFlow** 只知道打电话，不知道 CRM 是什么
- **n8n** 只知道处理数据，不知道 WebSocket 是什么
- 两者通过简单的 HTTP + JSON 解耦

换客户（换 CRM、换日历、换通知方式）只需要修改 n8n 工作流，零代码改动。这是构建可复用 AI 基础设施的关键原则。
