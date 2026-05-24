# 从零开始的白标 SaaS：一份代码服务多个客户

> **TL;DR**：通过环境变量驱动所有业务相关的配置（公司名、AI 身份、提示词、日历），同一套代码可以为不同客户部署为独立实例，无需 fork，无需改代码。

---

## 什么是白标（White-label）？

白标是指：你开发产品，客户贴上自己的品牌出售或使用。

对于 AI 语音接待员来说，白标意味着：
- 客户 A：AI 叫 "Sara"，代表 "Downtown Dental"
- 客户 B：AI 叫 "Alex"，代表 "City Physio Clinic"  
- 客户 C：AI 叫 "Emma"，代表 "North Star Insurance"

三个实例，**同一份代码**，**三套 `.env` 文件**。

---

## 第一阶段：最常见的硬编码错误

项目最初的状态：

```python
# ❌ 全部硬编码
SYSTEM_MESSAGE = """
You are Sara, an AI assistant for Dental Help 360.
Hello, thank you for calling Dental Help 360. My name is Sara...
Note: The time is 2026-01-15 09:30:00.  ← 启动时冻结！
"""
```

两个问题：
1. "Sara" 和 "Dental Help 360" 写死在代码里
2. 时间在服务**启动时**就计算好了，之后每次通话都用同一个时间

---

## 第二阶段：f-string 时间戳 Bug

为了让时间"动态"，写了这样的代码：

```python
import datetime

# 模块导入时执行一次
now = datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')

SYSTEM_MESSAGE = f"""
...
Note: The time and date now are {now}.   ← f-string 在这里求值
"""

# 后来想到要让时间刷新，加了这个函数
def get_stage_prompt(stage_type, current_time=None):
    if current_time is None:
        current_time = datetime.datetime.now(...)
    return MAINCONVO_PROMPT.format(now=current_time)  # ← 这行没有效果！
```

问题在哪？`MAINCONVO_PROMPT = f"...{now}..."` 在**模块加载时** `{now}` 就已经被替换成了具体时间字符串。后面的 `.format(now=current_time)` 在字符串里已经找不到 `{now}` 占位符了，相当于空操作。

**修复**：不用 f-string，改用普通字符串模板：

```python
# ✅ 正确：不在模块级别求值
_SYSTEM_MESSAGE_TEMPLATE = """
...
Note: The time and date now are {now}.   ← 这是字面量 {now}，不是 f-string
"""

def get_system_prompt() -> str:
    now = datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')
    return _SYSTEM_MESSAGE_TEMPLATE.format(
        now=now,
        agent_name=AGENT_NAME,       # 来自 config
        company_name=COMPANY_NAME,   # 来自 config
    )
```

每次通话创建时调用 `get_system_prompt()`，时间戳是实时的。

---

## 第三阶段：完全环境变量驱动

### config.py 里的身份配置

```python
# 代理身份 — 覆盖这两个变量即可白标
AGENT_NAME: str = os.environ.get('AGENT_NAME', 'Sara')
COMPANY_NAME: str = os.environ.get('COMPANY_NAME', 'Dental Help 360')

# 首句问候语，默认使用 AGENT_NAME
DEFAULT_FIRST_MESSAGE: str = os.environ.get(
    'DEFAULT_FIRST_MESSAGE',
    f"Hey, this is {AGENT_NAME}. How can I assist you today?",
)
```

### 日历配置：从 JSON 字符串加载

```python
# 原来：硬编码字典
CALENDARS_LIST = {
    "LOCATION1": "CALENDAR_EMAIL1",
    "LOCATION2": "CALENDAR_EMAIL2",
}

# 现在：可以从环境变量覆盖
_calendars_json = os.environ.get('CALENDARS_JSON')
CALENDARS_LIST: dict[str, str] = (
    json.loads(_calendars_json) if _calendars_json else {
        "LOCATION1": "CALENDAR_EMAIL1",
    }
)
```

客户的 `.env` 文件：
```env
CALENDARS_JSON={"Downtown": "downtown@gmail.com", "Uptown": "uptown@gmail.com"}
```

---

## 部署模式：一客户一实例

```
GitHub repo (单一代码库)
    │
    ├── 部署到 Railway (客户 A)
    │       AGENT_NAME=Sara
    │       COMPANY_NAME=Downtown Dental
    │       TWILIO_PHONE_NUMBER=+14165550001
    │       N8N_WEBHOOK_URL=https://n8n-a.example.com/webhook/xxx
    │
    ├── 部署到 Railway (客户 B)
    │       AGENT_NAME=Alex
    │       COMPANY_NAME=City Physio
    │       TWILIO_PHONE_NUMBER=+14165550002
    │       N8N_WEBHOOK_URL=https://n8n-b.example.com/webhook/yyy
    │
    └── 部署到 Heroku (客户 C)
            AGENT_NAME=Emma
            COMPANY_NAME=North Star Insurance
            ...
```

每个实例完全独立：独立的 Twilio 号码、独立的 n8n 工作流、独立的 Ultravox 知识库、独立的环境变量。

---

## .env.example：白标的操作手册

一个完整的 `.env.example` 是白标产品的用户文档：

```env
# ── 必填 ──────────────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX
ULTRAVOX_API_KEY=your_ultravox_api_key
N8N_WEBHOOK_URL=https://your-n8n.com/webhook/your-uuid
PUBLIC_URL=https://your-app.railway.app

# ── Agent 身份（白标配置）──────────────────────────────────────────────────
AGENT_NAME=Sara
COMPANY_NAME=Dental Help 360
# DEFAULT_FIRST_MESSAGE=Hey, this is Sara. How can I assist you today?

# ── 日历（JSON 格式，location 名 → Google Calendar ID）──────────────────
# CALENDARS_JSON={"Downtown": "clinic@gmail.com", "Uptown": "clinic2@gmail.com"}
```

新客户拿到这个文件，10 分钟内就能部署自己的实例。

---

## 更进一步：提示词外化

如果不同客户需要完全不同的对话流程，可以进一步把 prompt 模板路径也做成环境变量：

```python
SYSTEM_PROMPT_PATH: str = os.environ.get('SYSTEM_PROMPT_PATH', 'prompts/default.txt')

def get_system_prompt() -> str:
    template = Path(SYSTEM_PROMPT_PATH).read_text()
    return template.format(now=..., agent_name=AGENT_NAME, company_name=COMPANY_NAME)
```

这样业务负责人可以直接编辑 txt 文件修改 AI 行为，不需要懂代码。

---

## 总结：白标 SaaS 的核心原则

1. **业务相关内容 = 环境变量**：公司名、AI 名、联系方式、日历、webhook URL
2. **动态内容 = 运行时计算**：时间戳、会话 ID、caller number
3. **结构性逻辑 = 代码**：WebSocket 处理、工具分发、错误处理

判断一段内容该放哪里的方法：**问自己"换一个客户，这个需要变吗？"**
- 需要变 → 环境变量
- 不需要变 → 代码

遵守这个原则，你的代码库规模永远只有一份，而部署规模可以线性增长。
