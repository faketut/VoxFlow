# Ultravox 内置 RAG：让 AI 打电话时能查知识库

> **TL;DR**：Ultravox 提供原生的 `queryCorpus` 工具，把文档上传到平台后，AI 在通话中可以实时检索相关内容回答用户问题，无需自己搭建 embedding + 向量数据库。

---

## 什么是 RAG？

RAG（Retrieval-Augmented Generation）是让 LLM 在生成回答时，先从外部知识库检索相关段落，再结合检索结果生成答案。

```
用户问题
    ↓
向量检索（在知识库里找相关段落）
    ↓
把检索结果注入 LLM 上下文
    ↓
LLM 基于真实文档回答，而不是"瞎编"
```

传统做法需要自己搭建：Embedding 服务 + 向量数据库（Pinecone/Weaviate/ChromaDB）+ 检索 API + 注入逻辑。

Ultravox 把这个全包了。

---

## Ultravox Corpus：托管知识库

在 Ultravox 控制台（或 API）上传文档后，Ultravox 自动：

1. 对文档做分块（chunking）
2. 计算 embedding
3. 存入向量数据库
4. 提供 `queryCorpus` 工具接口

你拿到一个 `corpus_id`，长这样：`da6de42d-7f32-449e-a77a-9b948f834946`。

---

## 注册 queryCorpus 工具

创建 Ultravox 通话时，在 `selectedTools` 里注册：

```python
def _build_selected_tools() -> list[dict]:
    return [
        {
            "toolName": "queryCorpus",          # Ultravox 平台内置工具名
            "parameterOverrides": {
                "corpus_id": ULTRAVOX_CORPUS_ID, # 你的知识库 ID
                "max_results": 5,                # 每次检索返回最多 5 个段落
            },
        },
        # ... 其他工具
    ]
```

`toolName: "queryCorpus"` 是 Ultravox 的内置工具，不需要你提供 HTTP endpoint 或 handler 代码，平台自己处理检索逻辑。

`max_results: 5` 控制每次检索注入多少段落。太多会撑爆上下文窗口，太少可能找不到相关内容。5 是平衡点。

---

## 在 Prompt 里指导 AI 使用工具

仅注册工具还不够，需要在 system prompt 里明确告诉 AI 何时调用：

```markdown
## Handling Questions
Use the function `queryCorpus` to respond to customer queries and questions
about insurance policies, clinic hours, pricing, and procedures.

Do NOT answer factual questions from memory. Always use queryCorpus first.
```

关键指令：**不要从记忆回答，总是先查知识库**。否则 AI 可能用训练数据里的通用知识回答，而不是你的业务文档，导致错误信息。

---

## 工具调用的内部流程

当用户问"你们周六开门吗？"，系统内部发生了什么：

```
用户说: "你们周六开门吗？"
    ↓
Ultravox ASR 转文字
    ↓
LLM 决策: 需要查知识库
    ↓
Ultravox 执行 queryCorpus(
    corpus_id="da6de42d...",
    query="Saturday hours clinic",
    max_results=5
)
    ↓
向量检索，返回相关段落:
    "Clinic hours: Mon-Fri 9am-6pm, Sat 10am-4pm"
    ↓
LLM 基于检索结果生成回答
    ↓
TTS 合成语音: "Yes, we're open Saturday from 10am to 4pm."
```

这整个过程在 Ultravox 平台内完成，VoxFlow 代码**不参与**检索，只是把工具注册好。

---

## 知识库内容建议

什么内容适合放进 Corpus：

| 内容类型 | 示例 |
|----------|------|
| 营业信息 | 地址、电话、营业时间 |
| 服务/产品目录 | 治疗项目、价格区间 |
| 常见问答 | "保险接受哪些"、"预约流程是什么" |
| 政策文件 | 退款政策、隐私政策 |
| 员工目录 | 医生简介、专业方向 |

**不适合**放进 Corpus 的内容：
- 实时数据（如今天的预约空位）→ 应该通过 n8n 工具实时查询
- 客户个人信息 → 安全风险，应该通过 API 查询
- 经常变动的价格 → 频繁更新麻烦，考虑用工具调用

---

## 多诊所场景：一个 Corpus per 客户

如果你给多个客户提供服务，每个客户有自己的 Corpus：

```env
# 客户 A
ULTRAVOX_CORPUS_ID=da6de42d-7f32-449e-a77a-9b948f834946

# 客户 B（换个 .env 文件即可）
ULTRAVOX_CORPUS_ID=e5f7a1b2-8c9d-4e3f-b0a1-2c3d4e5f6789
```

Corpus ID 是环境变量，换客户只需改 `.env`，代码零改动。

---

## 与自建 RAG 的对比

| 维度 | Ultravox 内置 RAG | 自建 RAG |
|------|-------------------|----------|
| 搭建时间 | 上传文档，5 分钟 | 1-3 天（选型 + 部署 + 集成） |
| 维护成本 | 零（Ultravox 负责） | 需维护向量数据库 |
| 定制化 | 有限（chunk 大小、检索策略） | 完全可控 |
| 延迟 | 内置优化，极低 | 取决于你的实现 |
| 成本 | 包含在 Ultravox 费用里 | 额外向量数据库费用 |
| 适合场景 | 文档稳定、知识库中等规模 | 复杂检索逻辑、多跳推理 |

对于大多数 AI 客服场景，Ultravox 内置 RAG 是最快的路径。

---

## 总结

Ultravox 的 `queryCorpus` 工具把 RAG 的基础设施复杂度降到零。你需要做的：

1. 在 Ultravox 控制台上传业务文档
2. 拿到 `corpus_id`，写入 `.env`
3. 在 `selectedTools` 里注册 `queryCorpus`
4. 在 prompt 里告诉 AI "遇到问题先查知识库"

剩下的 embedding、检索、注入全部由平台处理。
