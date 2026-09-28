# Provider integration notes

*[中文版](provider-notes.zh-CN.md)*

**Status:** the **Volcengine AgentPlan** path (Seedream 5.0 Lite) has been exercised
end-to-end against the live service — 18 real generations across three runs. Everything in
the AgentPlan section below is verified behaviour, including the failure modes. The OpenAI
and Gemini paths are still **unexercised**; their request shapes are written from
documentation.

This document records the **exact request shape** each engine sends, so you can diff
against it when something returns a 400.

Every request goes through the standard library `urllib`
([`dig/providers/base.py`](../dig/providers/base.py)). Errors print the server's raw
response body (truncated to 1200 chars), which usually names the offending field directly.
Add `-v` to any command to log outgoing payloads, with base64 blobs elided.

### Errors, retries and secrets

| Failure | What happens |
|---|---|
| HTTP 401 / 403 (key rejected, model not enabled) | Not retried. The **whole run stops** after that one request and exits 2 — the next eleven panels would fail the same way |
| HTTP 400 / 404 / 405 / 413 / 422 (bad request shape) | Not retried; that panel falls back to a placeholder and the run exits 1 |
| HTTP 408 / 429 / 5xx, dropped connections, read timeouts | Retried with exponential backoff (`run.attempts`) |

Error text is written into `manifest.json` and printed, so every message is passed through a
redactor first: `?key=` query parameters, `Bearer` tokens and Google-style `AIza…` keys are
replaced with `***`.

### Caching

The panel cache key is the prompt, size, seed, **the content of every reference image**,
and the engine identity (provider, model, base URL). A different model — or the offline
mock — never reuses another engine's pictures. Mock output is never cached at all. The
character-sheet cache is keyed the same way.

---

## 1. Volcengine Ark (the default provider)

[`dig/providers/ark.py`](../dig/providers/ark.py)

### Chat / vision

```
POST {base_url}/chat/completions
Authorization: Bearer $ARK_API_KEY
```

OpenAI-compatible. Image input goes in the `content` array as an `image_url` part whose
value is a `data:image/jpeg;base64,...` URI.

### Text-to-image / image-to-image

```
POST {base_url}/images/generations
Authorization: Bearer $ARK_API_KEY

{
  "model": "doubao-seedream-4-0-250828",
  "prompt": "...",
  "image": "data:image/jpeg;base64,...",   // an array when passing several references
  "size": "2008x1280",
  "response_format": "url",
  "watermark": false,
  "sequential_image_generation": "disabled",
  "seed": 12345
}
```

Returns `{"data": [{"url": "https://..."}]}`; the code downloads it. A `b64_json` response
is handled too.

### Likely adjustments

| Symptom | Where to change it |
|---|---|
| `model not found` | Set `providers.image.model` in `config.yaml` to your console's **inference endpoint ID** (`ep-2024xxxx-xxxxx`) rather than the public model name |
| `size` rejected | Seedream 4.0 wants 1280–4096 per side. Adjust `ARK_MIN_SIDE`/`ARK_MAX_SIDE` in `ark.py`, or switch to tier notation (`"size": "2K"`) via `providers.image.image_extra` |
| Multi-reference rejected | Set `max_ref_images: 1`; older models accept a single reference |
| Some other field needed | Add `providers.image.image_extra: {...}` in `config.yaml` — it is merged straight into the payload |

### AgentPlan (`/api/plan/v3`) — verified behaviour

AgentPlan is a **different API surface** from pay-as-you-go Ark. Four things differ, and
all four were found by hitting the live service:

| | Pay-as-you-go Ark | AgentPlan (Seedream 5.0 Lite) |
|---|---|---|
| Base URL | `/api/v3` | **`/api/plan/v3`** |
| `size` | 1280–4096 per side | **total pixels ≥ 3,686,400** (= 1920×1920); tiers `2K`/`3K`/`4K` or `WxH` |
| `output_format` | n/a | separate field (`jpeg`/`png`); `response_format` is fixed to `url` |
| `stream` | n/a | required on Lite (Pro rejects it, along with `sequential_image_generation`) |
| `seed` | supported | **not supported** — omit it |

The code picks its shape from the base URL, so both surfaces work from one provider:

```yaml
providers:
  image:
    provider: ark
    base_url: https://ark.cn-beijing.volces.com/api/plan/v3
    model: <your AgentPlan Seedream 5.0 Lite model ID>
    api_key_env: ARK_API_KEY
```

**Under-sized requests fail loudly and usefully:**

```
HTTP 400 InvalidParameter: The parameter `size` specified in the request is not
valid: image size must be at least 3686400 pixels
```

`plan_size()` in `ark.py` scales any panel aspect up to satisfy that while preserving the
ratio. A 1.57:1 panel becomes 2408×1536.

**Two failure modes worth knowing about:**

1. **Reference images must be compressed.** Passing a raw 2408×1536 PNG as a base64 data
   URI makes a ~0.8 MB body, and the gateway closes the connection without responding
   (`Remote end closed connection without response`). References are now downscaled to
   1024 px JPEG (~300 KB) before upload — tune with `providers.image.ref_max_side`.
2. **Image-to-image does not like concurrency.** With `workers: 2`, image-to-image calls
   dropped connections intermittently — 1 of 6 succeeded, then 3 of 6 after compression.
   At `workers: 1` with `attempts: 4`, all 6 succeeded (one needed three tries).
   **Set `run.workers: 1` when generating with reference images.** Text-to-image at
   `workers: 2` was fine, so this is specific to the image-to-image path.

Measured throughput: roughly **50–70 s per panel** serially, so a 12-panel set is about
6–10 minutes.

`image_extra` / `chat_extra` are the escape hatch: any unanticipated field can be injected
from config without touching code.

```yaml
providers:
  image:
    image_extra:
      size: "2K"
      sequential_image_generation: "auto"
```

---

## 2. OpenAI (and any OpenAI-compatible service)

[`dig/providers/openai_compat.py`](../dig/providers/openai_compat.py)

- Chat: `POST {base_url}/chat/completions`
- No reference image: `POST {base_url}/images/generations`, `model: gpt-image-1`
- **With reference images**: `POST {base_url}/images/edits`, `multipart/form-data`, field
  name `image[]`

gpt-image-1 accepts only `1024x1024`, `1024x1536` and `1536x1024`. The code picks the
closest aspect ratio and the compositor centre-crops afterwards, so the panel ratio is
unaffected.

DeepSeek, Moonshot, SiliconFlow and local vLLM/Ollama all work under `provider: openai` —
just point `base_url` at them. Most offer chat but not images, so a common setup is text
from one of those and images from Ark.

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

The image model is `gemini-2.5-flash-image`; output arrives at
`candidates[0].content.parts[*].inlineData.data` as base64. Gemini does not take pixel
dimensions, so the code appends an aspect-ratio instruction to the prompt instead.

The key travels in the `x-goog-api-key` header. It used to be a `?key=` query parameter,
which meant any HTTP error wrote the full URL — key included — into `manifest.json`,
`script.json` and the console.

**Character consistency is strongest here**, which makes it worth testing for personal-IP work.

---

## 4. mock (offline)

[`dig/providers/mock.py`](../dig/providers/mock.py). No network. Placeholder art is
generated deterministically from the prompt hash, and the text engine produces a
structurally valid fake script by reading the `【生成参数】{...}` JSON block embedded in the
prompt. It reports `billed = False`: its output is never written to the image cache and it
skips the post-generation quality check (placeholders are flat colour blocks by design).

It exists for two reasons:

1. Verifying layout, fonts and export without spending anything.
2. Falling back when a real engine repeatedly fails on one panel
   (`run.fallback_to_mock`), so a six-image set always completes instead of stalling halfway.

---

## Switching providers

Only `config.yaml` changes. The three roles can each point at a different vendor:

```yaml
providers:
  text:   { provider: openai, model: gpt-4.1,          base_url: https://api.openai.com/v1, api_key_env: OPENAI_API_KEY }
  vision: { provider: gemini, model: gemini-2.5-flash, api_key_env: GEMINI_API_KEY }
  image:  { provider: ark,    model: ep-2024xxxx-xxxxx, api_key_env: ARK_API_KEY }
```

To add a brand-new service, implement `TextEngine.complete()` and `ImageEngine.generate()`
following [`dig/providers/mock.py`](../dig/providers/mock.py), then register the name in
[`dig/providers/__init__.py`](../dig/providers/__init__.py). Raise
`HTTPStatusError(status, message)` for HTTP failures (`http_json` already does) so the
retry and fail-fast rules above apply. Nothing else needs to change.
