# 用 Pydantic v2 保护 AI 工具调用的入参

> **TL;DR**：LLM 生成的 JSON 参数不可信。用 Pydantic v2 模型做 schema 校验，配合注册表模式，可以让工具调用代码既安全又易于扩展。

---

## 为什么需要校验 AI 的输出？

当 AI 调用工具时，它生成的 JSON 参数本质上是模型的"猜测"。即使 prompt 写得很清楚，LLM 仍然可能：

- 漏掉必填字段（"它上次没报错所以我不填了"）
- 字段类型错误（应该是字符串却传了数字）
- 传入意外的额外字段（从其他工具的参数"混入"）
- 传入空字符串当有效值

如果不校验就直接用，轻则 bug 难以定位，重则把错误数据写入 CRM 或发出错误预约邮件。

---

## 工具参数模型

每个工具对应一个 Pydantic `BaseModel`：

```python
from pydantic import BaseModel, Field


class VerifyParams(BaseModel):
    full_name: str = ""
    phone_number: str = ""


class ScheduleMeetingParams(BaseModel):
    name: str = Field(...)        # 必填
    email: str = Field(...)
    purpose: str = Field(...)
    datetime: str = Field(...)
    location: str = Field(...)


class QueryCorpusParams(BaseModel):
    question: str | None = None   # 可选
```

Pydantic v2 的好处：
- `Field(...)` 表示必填，缺失时直接抛 `ValidationError`
- `str | None` 明确表达"可以是 None"
- 自动类型转换（`"42"` → `42` 等）
- 错误信息清晰，方便调试

---

## 注册表模式：TOOL_HANDLERS

把工具名映射到`(参数模型, handler 函数)`的元组：

```python
from typing import Awaitable, Callable

# handler 的类型签名
ToolHandler = Callable[[Any, str, BaseModel], Awaitable[None]]

TOOL_HANDLERS: dict[str, tuple[type[BaseModel], ToolHandler]] = {
    "verify":               (VerifyParams,           handle_verify),
    "queryCorpus":          (QueryCorpusParams,       handle_queryCorpus),
    "schedule_meeting":     (ScheduleMeetingParams,   handle_schedule_meeting),
    "move_to_main_convo":   (MoveToMainConvoParams,   handle_move_to_main_convo),
    "move_to_call_summary": (MoveToCallSummaryParams, handle_move_to_call_summary),
    "hangUp":               (HangUpParams,            handle_hang_up),
}
```

注册表的价值：**添加新工具只需两步**，不需要修改分发逻辑：

```python
# 1. 定义参数模型和 handler
class SendSmsParams(BaseModel):
    phone: str = Field(..., pattern=r"^\d{10}$")
    message: str

async def handle_send_sms(uv_ws, invocation_id, params: SendSmsParams):
    await sms_service.send(params.phone, params.message)
    await _send_tool_result(uv_ws, invocation_id, "SMS sent.")

# 2. 注册
TOOL_HANDLERS["sendSms"] = (SendSmsParams, handle_send_sms)
```

---

## 统一分发入口

所有工具调用都经过同一个入口函数，在这里做校验和分发：

```python
async def handle_tool_invocation(
    uv_ws: Any,
    tool_name: str,
    invocation_id: str,
    parameters: dict,
) -> None:
    # 1. 查注册表
    entry = TOOL_HANDLERS.get(tool_name)
    if not entry:
        logger.warning("Unknown tool: %s", tool_name)
        await _send_tool_error(uv_ws, invocation_id, f"Unknown tool: {tool_name}")
        return

    ParamsModel, handler = entry

    # 2. Pydantic 校验
    try:
        params = ParamsModel(**parameters)
    except ValidationError as e:
        logger.warning("Invalid params for %s: %s", tool_name, e)
        # 特殊处理：schedule_meeting 缺字段时，让 AI 重新收集
        if tool_name == "schedule_meeting":
            missing = [err["loc"][0] for err in e.errors()]
            msg = f"Please collect the following missing information: {', '.join(missing)}"
            await _send_tool_result(uv_ws, invocation_id, msg)
        else:
            await _send_tool_error(uv_ws, invocation_id, "Invalid parameters.")
        return

    # 3. 执行，捕获所有异常
    try:
        await handler(uv_ws, invocation_id, params)
    except Exception:
        logger.exception("Tool handler %s failed", tool_name)
        await _send_tool_error(uv_ws, invocation_id, "An internal error occurred.")
```

注意三层防护：
1. **未知工具**：查注册表失败 → 返回错误，不崩溃
2. **参数错误**：Pydantic 校验失败 → 可以让 AI 重新收集，而不是报 500
3. **Handler 异常**：try/except 兜底 → 记录日志，通话继续

---

## 特殊处理：缺字段时引导 AI 补充

`schedule_meeting` 需要 5 个字段，AI 可能在信息收集不完整时就调用工具。普通报错会让通话陷入僵局，更好的做法是把缺失字段告诉 AI，让它继续向用户收集：

```python
if tool_name == "schedule_meeting":
    missing = [err["loc"][0] for err in e.errors()]
    # 发给 Ultravox 的 tool_result，AI 会用这条消息继续对话
    msg = f"Please collect: {', '.join(missing)} before booking."
    await _send_tool_result(uv_ws, invocation_id, msg)
```

结果：用户听到的是"我还需要您的邮箱地址才能完成预约"，而不是沉默或报错音。

---

## 测试：Pydantic 模型是最易测试的部分

工具参数模型是纯函数，不依赖任何外部服务，测试极其简单：

```python
# tests/test_tools_service.py

def test_schedule_meeting_requires_all_fields():
    with pytest.raises(ValidationError):
        ScheduleMeetingParams(name="John")  # 缺 email、purpose 等

def test_verify_params_defaults_to_empty():
    p = VerifyParams()
    assert p.full_name == ""
    assert p.phone_number == ""

def test_schedule_meeting_valid():
    p = ScheduleMeetingParams(
        name="Jane", email="jane@example.com",
        purpose="checkup", datetime="2026-06-01 10:00",
        location="Downtown",
    )
    assert p.location == "Downtown"
```

这些测试不需要 mock，不需要网络，运行极快。是整个测试套件里性价比最高的部分。

---

## 总结

| 模式 | 优点 |
|------|------|
| Pydantic 参数模型 | 类型安全、自动验证、错误信息清晰 |
| `TOOL_HANDLERS` 注册表 | 新增工具不改分发逻辑，一处修改 |
| 统一分发入口 | 所有工具共享错误边界和日志 |
| 校验失败 → 引导 AI | 比直接报错有更好的用户体验 |

AI 的输出永远是"不可信的外部输入"，用 Pydantic 在边界处校验，是构建健壮 AI 工具系统的基本原则。
