# Python 3.11 asyncio.TaskGroup：并发处理双向 WebSocket 流

> **TL;DR**：用 `asyncio.TaskGroup` + `except*` 管理两个并发 WebSocket 连接，比手动 `gather` + `cancel` 更安全、更易读，也是处理双向流媒体的正确模式。

---

## 问题：两个 WebSocket，一个会话

AI 语音通话需要同时处理两个 WebSocket：

- **Twilio WebSocket**：持续接收用户的麦克风音频，发送 AI 的合成音频
- **Ultravox WebSocket**：持续发送用户音频给 AI，接收 AI 的响应

这两个连接的生命周期必须绑定在一起：
- 用户挂断 → Twilio 断开 → Ultravox 也应该断开
- Ultravox 出错 → 应该通知 Twilio 结束通话
- 任意一端异常 → 清理资源，不留僵尸连接

---

## 反面教材：手动 gather + cancel

在 Python 3.10 之前，常见写法是这样：

```python
# ❌ 容易出问题的写法
async def media_stream(websocket):
    await websocket.accept()
    state = setup_state(websocket)

    twilio_task = asyncio.create_task(_handle_twilio(state))
    uv_task = asyncio.create_task(_handle_ultravox(state))

    try:
        await asyncio.gather(twilio_task, uv_task)
    except Exception as e:
        # 问题：gather 只抛出第一个异常，另一个任务继续跑
        twilio_task.cancel()
        uv_task.cancel()
        await asyncio.gather(twilio_task, uv_task, return_exceptions=True)
    finally:
        await _cleanup(state)
```

这种写法的问题：
1. `gather` 默认在第一个异常时取消其他任务，但不等待它们完成
2. 取消是异步的，`cancel()` 后立刻 `gather` 可能没等到取消完成
3. 两个任务同时抛出异常时，只能看到其中一个

---

## 正确写法：asyncio.TaskGroup（Python 3.11+）

```python
# ✅ 使用 TaskGroup
async def media_stream(websocket: WebSocket):
    await websocket.accept()
    state = CallState(twilio_ws=websocket, ...)

    try:
        async with asyncio.TaskGroup() as tg:
            twilio_task = tg.create_task(_handle_twilio(state))
            tg.create_task(_handle_ultravox_when_ready(state, twilio_task))
    except* WebSocketDisconnect:
        pass  # 正常断开，不记为错误
    except* Exception as eg:
        for exc in eg.exceptions:
            logger.exception("Session error: %s", exc)
    finally:
        await _cleanup(state)
```

`TaskGroup` 的保证：
- **任意任务抛出异常 → 立即取消其他所有任务**
- **等待所有任务真正完成后才退出 `async with` 块**
- **收集所有任务的异常 → 打包成 `ExceptionGroup` 一起抛出**

---

## except*：异常组语法（Python 3.11）

`except*` 是专门为 `ExceptionGroup` 设计的新语法：

```python
try:
    async with asyncio.TaskGroup() as tg:
        tg.create_task(task_a())
        tg.create_task(task_b())
except* ValueError as eg:
    # eg.exceptions 是所有 ValueError 实例的列表
    for e in eg.exceptions:
        print(f"ValueError: {e}")
except* ConnectionError as eg:
    # 可以同时有多个 except* 分支
    for e in eg.exceptions:
        print(f"ConnectionError: {e}")
```

与普通 `except` 的区别：
- `except Exception`：匹配第一个异常类型，吃掉整个组
- `except* Exception`：只匹配组中属于该类型的异常，其余继续传播

---

## 处理启动顺序依赖

Ultravox WebSocket 的地址（`joinUrl`）需要在 Twilio `start` 消息到来后才能从 session 里拿到。两个任务有顺序依赖，但又要并发运行。

解决方案：用 `asyncio.Event` 作为启动信号：

```python
@dataclass
class CallState:
    twilio_ws: WebSocket
    # ...
    uv_ws: Any | None = None
    started: asyncio.Event = field(default_factory=asyncio.Event)


async def _handle_twilio(state: CallState):
    async for message in state.twilio_ws.iter_json():
        event = message.get("event")
        if event == "start":
            await _on_twilio_start(state, message)
            state.started.set()  # ← 通知 Ultravox 任务可以开始了
        elif event == "media" and state.uv_ws:
            await _on_twilio_media(state, message["media"]["payload"])


async def _handle_ultravox_when_ready(state: CallState, twilio_task):
    await state.started.wait()  # ← 等待 start 事件

    join_url = state.session.get("uvJoinUrl")
    async with websockets.connect(join_url) as uv_ws:
        state.uv_ws = uv_ws
        async for message in uv_ws:
            await _handle_ultravox_message(state, message)
```

`asyncio.Event` 是最轻量的协程间同步原语，不需要锁，零开销。

---

## 清理：finally 块的重要性

无论正常结束、用户挂断、还是异常崩溃，都必须执行清理：

```python
async def _cleanup(state: CallState) -> None:
    # 1. 关闭 Ultravox WebSocket
    if state.uv_ws:
        await safe_close_websocket(state.uv_ws, "ultravox")

    # 2. 从 SessionManager 移除会话
    if state.call_sid:
        session = await session_manager.pop(state.call_sid)
        # 3. 发送通话摘要到 n8n
        if session and not session.get("transcript_sent"):
            await send_transcript_to_n8n(session)
```

`finally` 块保证无论怎么退出都会执行，但注意：`finally` 里不应该 `await` 可能无限阻塞的操作，因此 `safe_close_websocket` 内部有超时：

```python
async def safe_close_websocket(ws, name: str, timeout: float = 3.0):
    try:
        if ws.state == State.OPEN:
            await asyncio.wait_for(ws.close(), timeout=timeout)
    except (asyncio.TimeoutError, Exception):
        pass  # 关不了就算了，连接已经死了
```

---

## 总结

| 方案 | Python 版本 | 问题 |
|------|------------|------|
| `asyncio.gather` | 3.7+ | 异常处理不完整，资源泄漏风险 |
| `asyncio.TaskGroup` | 3.11+ | 自动取消 + 等待 + 收集所有异常 |

对于"任意一个子任务失败 = 整个会话结束"这种语义，`TaskGroup` 是标准答案。双向 WebSocket 流媒体是它最自然的应用场景之一。
