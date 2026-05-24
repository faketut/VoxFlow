# 用 Twilio + Ultravox 构建 AI 语音接待员

> **TL;DR**：把一个真实电话号码接到大语言模型，实现全自动语音接待，整个系统只需一个 FastAPI 服务，无需自己训练模型。

---

## 背景

传统 IVR（按键语音菜单）体验极差。用户按了一堆数字，最后还是被转到人工。能不能用 AI 直接接电话，自然对话、自动预约、自动归档？

这篇文章记录了我用 **Twilio**（电话基础设施）+ **Ultravox**（实时语音 AI）+ **FastAPI**（中间件服务）构建 AI 语音接待员的完整过程。

---

## 系统架构

```
来电
 │
 ▼
Twilio ──POST──▶ FastAPI /incoming-call
                    │
                    ├─ 1. 向 n8n 查询个性化首句话
                    ├─ 2. 调用 Ultravox API 创建 AI 通话会话
                    └─ 3. 返回 TwiML，建立 Media Stream
                              │
                              ▼
              Twilio Media Stream WebSocket (/media-stream)
                    │                         │
              接收麦克风音频              接收 AI 合成音频
                    └────────── 双向转发 ──────┘
                                    │
                               工具调用
                          （预约 / 查询 / 挂断）
```

三个角色分工清晰：
- **Twilio**：负责电话网络，把音频变成 WebSocket 流
- **Ultravox**：负责 ASR + LLM + TTS，处理语音理解和生成
- **FastAPI 服务**：胶水层，连接两端，处理业务工具调用

---

## 第一步：接入来电

Twilio 在有电话打来时，向你配置的 URL 发一个 POST 请求。你返回 TwiML XML 告诉 Twilio 怎么处理这个通话。

```python
# app/api/endpoints/calls.py

@router.post("/incoming-call")
async def incoming_call(request: Request) -> Response:
    form_data = await request.form()
    caller_number = form_data.get("From", "Unknown")

    # 向 n8n 获取动态首句问候语
    first_message = await _fetch_first_message_from_n8n(caller_number)

    # 创建 Ultravox 会话，拿到 joinUrl
    join_url = await create_ultravox_call(
        system_prompt=get_system_prompt(),
        first_message=first_message,
    )

    # 返回 TwiML，让 Twilio 把音频流导向我们的 WebSocket
    twiml = _build_stream_twiml(
        stream_url=f"wss://{PUBLIC_URL}/media-stream",
        first_message=first_message,
        caller_number=caller_number,
    )
    return Response(content=twiml, media_type="application/xml")
```

`_build_stream_twiml` 用 Twilio 官方 SDK 生成 XML，避免手拼字符串导致注入漏洞：

```python
def _build_stream_twiml(stream_url, first_message, caller_number):
    response = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=stream_url)
    stream.parameter(name="firstMessage", value=first_message)
    stream.parameter(name="callerNumber", value=caller_number)
    response.append(connect)
    return str(response)
```

---

## 第二步：双向音频桥接

Twilio 建立 Media Stream 后，会持续发送 WebSocket 消息（JSON 包裹 base64 音频）。我们同时要连接 Ultravox 的 WebSocket，把音频双向转发。

```python
# app/websockets/media_stream.py

@dataclass
class CallState:
    twilio_ws: WebSocket
    call_sid: str
    stream_sid: str
    session: dict
    uv_ws: Any | None = None
    twilio_active: bool = True
    ultravox_active: bool = True
    started: asyncio.Event = field(default_factory=asyncio.Event)


async def media_stream(websocket: WebSocket):
    await websocket.accept()
    state = CallState(twilio_ws=websocket, ...)

    async with asyncio.TaskGroup() as tg:
        twilio_task = tg.create_task(_handle_twilio(state))
        tg.create_task(_handle_ultravox_when_ready(state, twilio_task))
```

两个协程并发运行，`asyncio.TaskGroup` 保证任意一个崩溃时另一个也被取消，不会出现僵尸任务。

---

## 第三步：创建 Ultravox 会话

Ultravox 是一个"serverless 语音 AI"服务。一个 API 调用就能创建一个有完整 ASR + LLM + TTS 能力的实时会话：

```python
async def create_ultravox_call(system_prompt: str, first_message: str) -> str:
    payload = {
        "systemPrompt": system_prompt,
        "model": "fixie-ai/ultravox-70B",
        "voice": "Tanya-English",
        "initialMessages": [{"role": "MESSAGE_ROLE_USER", "text": first_message}],
        "medium": {
            "serverWebSocket": {
                "inputSampleRate": 8000,   # 匹配 Twilio 的 8kHz
                "outputSampleRate": 8000,
            }
        },
        "selectedTools": _build_selected_tools(),  # 注册工具
    }
    resp = await client.post(ULTRAVOX_CALLS_URL, headers=headers, json=payload)
    return resp.json()["joinUrl"]  # WebSocket 地址
```

---

## 第四步：工具调用

当 AI 判断需要执行某个动作（如预约、查询），会发送一个 tool invocation 消息。我们拦截并处理：

```python
async def _handle_ultravox_text(state: CallState, message: str):
    data = json.loads(message)
    if data.get("type") == "client_tool_invocation":
        await handle_tool_invocation(
            uv_ws=state.uv_ws,
            tool_name=data["toolName"],
            invocation_id=data["invocationId"],
            parameters=data.get("parameters", {}),
        )
```

每个工具都用 Pydantic 模型校验参数，然后调用对应 handler，最后把结果发回给 Ultravox。

---

## 部署

项目有 `Procfile`，可以直接部署到 Heroku 或 Railway：

```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

必填环境变量：

```env
TWILIO_ACCOUNT_SID=ACxxxx
TWILIO_AUTH_TOKEN=xxxx
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX
ULTRAVOX_API_KEY=xxxx
N8N_WEBHOOK_URL=https://your-n8n.com/webhook/xxx
PUBLIC_URL=https://your-app.railway.app
```

---

## 总结

| 组件 | 职责 | 替代方案 |
|------|------|----------|
| Twilio | 电话网络接入、音频流 | Vonage、SignalWire |
| Ultravox | ASR + LLM + TTS 一体化 | Deepgram + OpenAI + ElevenLabs（更复杂） |
| FastAPI | 中间件、工具调用、业务逻辑 | Flask、Node.js |
| n8n | 下游工作流自动化 | Zapier、Make |

这套架构的最大优点是**解耦**：换掉任何一个组件不影响其他部分。AI 不好用？换模型。不用 Twilio？换 SDK，WebSocket 协议不变。
