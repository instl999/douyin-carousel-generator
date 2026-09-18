# 引擎对接备忘


*[English](provider-notes.md)*

**重要**：这份代码写好时本机没有 Python 运行环境，所有 HTTP 请求**没有对着真实服务打过**。
离线流程（mock 引擎 + 排版 + 导出）逻辑完整，但真实 API 的字段名/取值有可能需要按
你账号开通的版本微调。这份文档写清了每个引擎用的**确切请求形状**，出错时照着对就行。

所有请求都走标准库 `urllib`（`dig/providers/base.py`），报错会把服务端返回的
响应体原文打出来（截断 1200 字符），一般能直接看出是哪个字段不对。
调试时加 `-v` 会打印发出去的 payload（base64 自动截断）。

---

## 1. 火山方舟 Ark（默认）

`dig/providers/ark.py`

### 对话 / 视觉

```
POST {base_url}/chat/completions
Authorization: Bearer $ARK_API_KEY
```

OpenAI 兼容格式。图片输入走 `content` 数组里的 `image_url`，值是 `data:image/jpeg;base64,...`。

### 文生图 / 图生图

```
POST {base_url}/images/generations
Authorization: Bearer $ARK_API_KEY

{
  "model": "doubao-seedream-4-0-250828",
  "prompt": "...",
  "image": "data:image/jpeg;base64,..."   // 或多张时是数组
  "size": "2008x1280",
  "response_format": "url",
  "watermark": false,
  "sequential_image_generation": "disabled",
  "seed": 12345
}
```

返回 `{"data": [{"url": "https://..."}]}`，代码会把图下载回来；
返回 `b64_json` 也能处理。

**可能需要调的地方**

| 症状 | 改哪里 |
|---|---|
| `model not found` | `config.yaml` 的 `providers.image.model` 换成你控制台里的**推理接入点 ID**（`ep-2024xxxx-xxxxx`） |
| `size` 报错 | Seedream 4.0 单边要求 1280~4096。代码里 `ARK_MIN_SIDE/ARK_MAX_SIDE` 可改；也可以改成 `"size": "2K"` 这种档位写法（在 `providers.image.image_extra` 里覆盖） |
| 多图参考报错 | 把 `max_ref_images` 调成 1；老版本模型只收单张 |
| 需要传别的字段 | `config.yaml` 里加 `providers.image.image_extra: {...}`，会直接 merge 进 payload |

`image_extra` / `chat_extra` 是逃生舱：任何没预料到的字段都能从配置塞进去，不用改代码。

```yaml
providers:
  image:
    image_extra:
      size: "2K"
      sequential_image_generation: "auto"
```

---

## 2. OpenAI（以及任何 OpenAI 兼容服务）

`dig/providers/openai_compat.py`

- 对话：`POST {base_url}/chat/completions`
- 无参考图：`POST {base_url}/images/generations`，`model: gpt-image-1`
- **有参考图**：`POST {base_url}/images/edits`，`multipart/form-data`，字段名 `image[]`

gpt-image-1 只接受 `1024x1024` / `1024x1536` / `1536x1024`，
代码会挑比例最接近的那个，再由排版阶段居中裁切，所以画格比例不受影响。

DeepSeek、Moonshot、硅基流动、本地 vLLM / Ollama 都可以用 `provider: openai`，
只要把 `base_url` 指过去。它们多数只有对话没有图像，可以文案用它们、画图用 Ark。

---

## 3. Gemini

`dig/providers/gemini.py`

```
POST {base}/models/{model}:generateContent?key=$GEMINI_API_KEY

{"contents": [{"role": "user", "parts": [
   {"text": "..."},
   {"inline_data": {"mime_type": "image/jpeg", "data": "<base64>"}}
]}]}
```

图像模型用 `gemini-2.5-flash-image`，返回在
`candidates[0].content.parts[*].inlineData.data`（base64）。
Gemini 不接受像素尺寸，代码改成在 prompt 里写「画幅比例：3:2」这类文字引导。

**角色一致性是这家最强**，做个人 IP 值得试。

---

## 4. mock（离线）

`dig/providers/mock.py`。不联网，按 prompt 哈希生成确定性占位图，
文本引擎按提示词里埋的 `【生成参数】{...}` JSON 产出结构正确的假脚本。

它存在的意义有两个：
1. 让你在不花一分钱的情况下验证排版、字体、导出是否正常；
2. 真实引擎某一格反复失败时兜底（`run.fallback_to_mock`），
   保证一套 6 张能出完整，而不是出一半卡住。

---

## 换引擎的最小改动

只改 `config.yaml`，三个环节可以分别指不同家：

```yaml
providers:
  text:   { provider: openai, model: gpt-4.1,   base_url: https://api.openai.com/v1, api_key_env: OPENAI_API_KEY }
  vision: { provider: gemini, model: gemini-2.5-flash,       api_key_env: GEMINI_API_KEY }
  image:  { provider: ark,    model: ep-2024xxxx-xxxxx,      api_key_env: ARK_API_KEY }
```

要接一家全新的服务，照着 `dig/providers/mock.py` 实现
`TextEngine.complete()` 和 `ImageEngine.generate()` 两个方法，
再在 `dig/providers/__init__.py` 里注册名字即可，其余代码不用动。
