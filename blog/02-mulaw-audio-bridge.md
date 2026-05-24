# μ-law 编解码：电话音频和 AI 模型的桥接原理

> **TL;DR**：电话网络用 8kHz μ-law 压缩音频，AI 模型要 PCM 16-bit 线性音频。这两个世界之间需要一个实时转换层，而 Python 的 `audioop` 模块（或其继任者 `audioop-lts`）就是这个桥。

---

## 为什么电话音频和 AI 音频格式不同？

### 电话网络：为 1960 年代设计的 8kHz μ-law

公共交换电话网络（PSTN）设计于模拟时代。数字化后，选定的标准是：

- **采样率**：8000 Hz（人声频率范围 300–3400 Hz，奈奎斯特定理够用）
- **编码**：μ-law（G.711），8 bit/样本
- **带宽**：64 Kbps

μ-law 是一种**对数压缩**编码。它对小信号（安静的声音）分配更多量化级别，对大信号（响亮的声音）压缩更多，模拟人耳对音量的感知特性。

```
线性 PCM 值（16-bit）: -32768 ~ +32767
               ↓  μ-law 压缩
μ-law 编码值（8-bit）:  0 ~ 255
```

### AI 模型：需要线性 PCM

语音 AI（ASR、TTS）模型在训练时使用的是未压缩的**线性 PCM**（通常 16-bit，16kHz 或 8kHz）。如果直接把 μ-law 字节喂给模型，它会认为这是随机噪声。

---

## Twilio 发来的音频格式

Twilio Media Stream 发送的 WebSocket 消息结构如下：

```json
{
  "event": "media",
  "streamSid": "MX...",
  "media": {
    "track": "inbound",
    "chunk": "42",
    "timestamp": "1234567890",
    "payload": "//5e/v7+..."   ← base64 编码的 μ-law 字节
  }
}
```

`payload` 是 base64(μ-law 8kHz 音频)。解码步骤：

```
base64 字符串
    ↓ base64.b64decode()
μ-law 字节 (8-bit, 8kHz)
    ↓ audioop.ulaw2lin(data, 2)
PCM 字节 (16-bit signed, 8kHz)
    ↓ 发送给 Ultravox WebSocket
```

---

## 代码实现

```python
# Twilio → Ultravox（用户说话）
async def _on_twilio_media(state: CallState, payload_b64: str) -> None:
    mu_law_bytes = base64.b64decode(payload_b64)
    # ulaw2lin(data, width): width=2 表示输出 16-bit (2 bytes/sample)
    pcm_bytes = audioop.ulaw2lin(mu_law_bytes, 2)
    await state.uv_ws.send(pcm_bytes)


# Ultravox → Twilio（AI 说话）
async def _forward_agent_audio(state: CallState, audio_bytes: bytes) -> None:
    # lin2ulaw(data, width): width=2 表示输入 16-bit
    mu_law_bytes = audioop.lin2ulaw(audio_bytes, 2)
    payload = base64.b64encode(mu_law_bytes).decode("utf-8")
    await state.twilio_ws.send_json({
        "event": "media",
        "streamSid": state.stream_sid,
        "media": {"payload": payload},
    })
```

---

## Python 3.13 的 audioop 问题

`audioop` 是 CPython 的 C 扩展模块，提供高效的音频操作。但它在 Python 3.11 被标记为 deprecated，**在 Python 3.13 中已被彻底移除**。

解决方案：用 `audioop-lts` 包（社区维护的纯 Python 替代，API 完全兼容）：

```python
try:
    import audioop          # Python < 3.13：用内置 C 扩展
except ModuleNotFoundError:
    import audioop_lts as audioop  # Python 3.13+：用兼容包
```

```
# requirements.txt
audioop-lts>=0.2.1
```

这个 try/except 模式是**向前兼容**的最佳实践：现有环境无感知，新环境自动切换。

---

## 采样率陷阱

Twilio 固定输出 8kHz，但 Ultravox 默认期望的采样率需要在创建会话时声明：

```python
"medium": {
    "serverWebSocket": {
        "inputSampleRate": 8000,   # 告诉 Ultravox 我们发来的是 8kHz
        "outputSampleRate": 8000,  # 告诉 Ultravox 输出也用 8kHz
        "clientBufferSizeMs": 60,  # 客户端缓冲 60ms，平衡延迟与抖动
    }
}
```

如果采样率不匹配，AI 说话会变成花栗鼠或慢动作，这是最常见的调试问题之一。

---

## 延迟分析

整条链路的端到端延迟（粗略）：

```
用户说话结束
  → Twilio 发送最后一帧 (< 20ms)
  → FastAPI 解码 μ-law → PCM (< 1ms)
  → Ultravox 收到音频，VAD 检测到说话结束 (384ms，可配置)
  → LLM 推理 + TTS 生成首帧 (300~800ms，取决于响应长度)
  → FastAPI 编码 PCM → μ-law (< 1ms)
  → Twilio 播放给用户
总计: ~700ms ~ 1.2s
```

`ULTRAVOX_TURN_ENDPOINT_DELAY=0.384s` 是 VAD（语音活动检测）的端点延迟，控制 AI 判断用户说完话需要等多久。太短会被打断，太长感觉迟钝。

---

## 总结

电话 AI 系统中的音频处理看似简单，实际有三个独立的问题需要同时解决：

1. **格式转换**：μ-law ↔ PCM（`audioop`）
2. **采样率协商**：双端必须约定好 8kHz 或 16kHz
3. **实时性**：转换必须在毫秒级完成，不能用队列缓冲

`audioop` 只做一件事但做得极快，是这个场景下的正确工具。
