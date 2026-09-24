# 引擎对接备忘


*[English](provider-notes.md)*

**现状**：**火山方舟 AgentPlan** 这条路（Seedream 5.0 Lite）已经对着线上服务完整跑通 ——
三轮共 18 次真实生成。下面 AgentPlan 一节写的都是实测行为，包括它的失败方式。
OpenAI 和 Gemini 两条路**还没实测**，请求形状是照文档写的。

这份文档写清了每个引擎发出去的**确切请求形状**，遇到 400 时照着对就行。

所有请求都走标准库 `urllib`（[`dig/providers/base.py`](../dig/providers/base.py)），
报错会把服务端返回的响应体原文打出来（截断 1200 字符），一般能直接看出是哪个字段不对。
调试时加 `-v` 会打印发出去的 payload（base64 自动截断）。

### 报错、重试和密钥

| 失败 | 怎么处理 |
|---|---|
| HTTP 401 / 403（Key 被拒、模型没开通） | 不重试。发了这一次请求就**整批停下**，退出码 2 —— 后面十一格只会同样失败 |
| HTTP 400 / 404 / 405 / 413 / 422（请求格式不对） | 不重试；这一格用占位图兜底，退出码 1 |
| HTTP 408 / 429 / 5xx、连接中断、读超时 | 按 `run.attempts` 指数退避重试 |

报错信息会写进 `manifest.json`、打到控制台，所以每条都先脱敏：
URL 里的 `?key=`、`Bearer` 令牌、Google 风格的 `AIza…` Key 一律换成 `***`。

### 缓存

每格缓存的键 = 提示词 + 尺寸 + seed + **每张参考图的内容** + 引擎身份（服务商、模型、base_url）。
换一个模型、或者从离线 mock 换成真引擎，都不会复用别人画的图。mock 的图根本不进缓存。
定妆图的缓存键同理。

---

## 1. 火山方舟 Ark（默认服务商）

[`dig/providers/ark.py`](../dig/providers/ark.py)

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
  "image": "data:image/jpeg;base64,...",   // 多张参考图时是数组
  "size": "2008x1280",
  "response_format": "url",
  "watermark": false,
  "sequential_image_generation": "disabled",
  "seed": 12345
}
```

返回 `{"data": [{"url": "https://..."}]}`，代码会把图下载回来；返回 `b64_json` 也能处理。

### 可能需要调的地方

| 症状 | 改哪里 |
|---|---|
| `model not found` | `config.yaml` 的 `providers.image.model` 换成你控制台里的**推理接入点 ID**（`ep-2024xxxx-xxxxx`） |
| `size` 报错 | Seedream 4.0 单边要求 1280~4096。代码里 `ARK_MIN_SIDE/ARK_MAX_SIDE` 可改；也可以改成 `"size": "2K"` 这种档位写法（在 `providers.image.image_extra` 里覆盖） |
| 多图参考报错 | 把 `max_ref_images` 调成 1；老版本模型只收单张 |
| 需要传别的字段 | `config.yaml` 里加 `providers.image.image_extra: {...}`，会直接 merge 进 payload |

### AgentPlan（`/api/plan/v3`）—— 实测行为

AgentPlan 和按量付费的 Ark 是**两套接口**，下面四处不同都是打线上服务打出来的：

| | 按量付费 Ark | AgentPlan（Seedream 5.0 Lite） |
|---|---|---|
| Base URL | `/api/v3` | **`/api/plan/v3`** |
| `size` | 单边 1280~4096 | **总像素 ≥ 3,686,400**（= 1920×1920）；档位 `2K`/`3K`/`4K` 或 `宽x高` |
| `output_format` | 无 | 单独字段（`jpeg`/`png`）；`response_format` 固定 `url` |
| `stream` | 无 | Lite 必填（Pro 传了会报错，`sequential_image_generation` 也是） |
| `seed` | 支持 | **不支持** —— 不要传 |

代码按 base_url 自动切换请求格式，同一个 provider 两套接口都能用：

```yaml
providers:
  image:
    provider: ark
    base_url: https://ark.cn-beijing.volces.com/api/plan/v3
    model: <你在 AgentPlan 控制台看到的 Seedream 5.0 Lite 模型 ID>
    api_key_env: ARK_API_KEY
```

**尺寸不够会明确报错：**

```
HTTP 400 InvalidParameter: The parameter `size` specified in the request is not
valid: image size must be at least 3686400 pixels
```

`ark.py` 里的 `plan_size()` 会保持比例把任意画格尺寸放大到满足要求，1.57:1 的画格会变成 2408×1536。

**两个值得知道的失败方式：**

1. **参考图必须压缩。** 把 2408×1536 的 PNG 原图 base64 直接塞进去，请求体约 0.8 MB，
   网关会不回响应直接断开（`Remote end closed connection without response`）。
   现在参考图上传前统一压成 1024 边长的 JPEG（约 300 KB），可用 `providers.image.ref_max_side` 调。
2. **图生图不喜欢并发。** `workers: 2` 时图生图请求会间歇性断连 —— 6 格只成 1 格，
   压缩参考图后是 3 格。`workers: 1` + `attempts: 4` 时 6 格全成（有一格试了三次）。
   **带参考图生成时设 `run.workers: 1`**（代码默认已经强制串行）。文生图在 `workers: 2` 下没问题，
   所以这是图生图特有的。

实测吞吐：串行每格大约 **50~70 秒**，一套 12 格约 6~10 分钟。

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

[`dig/providers/openai_compat.py`](../dig/providers/openai_compat.py)

- 对话：`POST {base_url}/chat/completions`
- 无参考图：`POST {base_url}/images/generations`，`model: gpt-image-1`
- **有参考图**：`POST {base_url}/images/edits`，`multipart/form-data`，字段名 `image[]`

gpt-image-1 只接受 `1024x1024` / `1024x1536` / `1536x1024`，
代码会挑比例最接近的那个，再由排版阶段居中裁切，所以画格比例不受影响。

DeepSeek、Moonshot、硅基流动、本地 vLLM / Ollama 都可以用 `provider: openai`，
只要把 `base_url` 指过去。它们多数只有对话没有图像，可以文案用它们、画图用 Ark。

---

## 3. Gemini

[`dig/providers/gemini.py`](../dig/providers/gemini.py)

```
POST {base}/models/{model}:generateContent
x-goog-api-key: $GEMINI_API_KEY

{"contents": [{"role": "user", "parts": [
   {"text": "..."},
   {"inline_data": {"mime_type": "image/jpeg", "data": "<base64>"}}
]}]}
```

图像模型用 `gemini-2.5-flash-image`，返回在
`candidates[0].content.parts[*].inlineData.data`（base64）。
Gemini 不接受像素尺寸，代码改成在 prompt 里写「画幅比例：3:2」这类文字引导。

Key 走 `x-goog-api-key` 请求头。以前拼在 URL 的 `?key=` 里：任何一次 HTTP 报错，
完整 URL（连同 Key）都会被写进 `manifest.json`、`script.json` 和控制台。

**角色一致性是这家最强**，做个人 IP 值得试。

---

## 4. mock（离线）

[`dig/providers/mock.py`](../dig/providers/mock.py)。不联网，按 prompt 哈希生成确定性占位图，
文本引擎按提示词里埋的 `【生成参数】{...}` JSON 产出结构正确的假脚本。
它标记为 `billed = False`：画的图绝不进缓存，也跳过出图后的质检（占位图本来就是色块）。

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
再在 `dig/providers/__init__.py` 里注册名字即可。HTTP 失败请抛
`HTTPStatusError(状态码, 信息)`（用 `http_json` 就自动是这样），上面的重试和整批停下规则才会生效。
其余代码不用动。
