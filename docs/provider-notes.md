# Provider integration notes

*[中文版](provider-notes.zh-CN.md)*

**Status:** the machine this was written on had no Python runtime, so **none of the HTTP
requests below have been exercised against live services.** The offline path (mock engine +
compositing + export) is covered by the test suite, but field names and accepted values on
the real APIs may need adjusting for whatever version your account has enabled. This
document records the **exact request shape** each engine sends, so you can diff against it
when something returns a 400.

Every request goes through the standard library `urllib`
([`dig/providers/base.py`](../dig/providers/base.py)). Errors print the server's raw
response body (truncated to 1200 chars), which usually names the offending field directly.
Add `-v` to any command to log outgoing payloads, with base64 blobs elided.

---

## 1. Volcengine Ark (default)

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
POST {base}/models/{model}:generateContent?key=$GEMINI_API_KEY

{"contents": [{"role": "user", "parts": [
   {"text": "..."},
   {"inline_data": {"mime_type": "image/jpeg", "data": "<base64>"}}
]}]}
```

The image model is `gemini-2.5-flash-image`; output arrives at
`candidates[0].content.parts[*].inlineData.data` as base64. Gemini does not take pixel
dimensions, so the code appends an aspect-ratio instruction to the prompt instead.

**Character consistency is strongest here**, which makes it worth testing for personal-IP work.

---

## 4. mock (offline)

[`dig/providers/mock.py`](../dig/providers/mock.py). No network. Placeholder art is
generated deterministically from the prompt hash, and the text engine produces a
structurally valid fake script by reading the `【生成参数】{...}` JSON block embedded in the
prompt.

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
[`dig/providers/__init__.py`](../dig/providers/__init__.py). Nothing else needs to change.
