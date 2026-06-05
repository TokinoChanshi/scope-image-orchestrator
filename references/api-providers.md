# API Provider Reference

This skill is endpoint-agnostic but the public implementation uses named,
official request shapes. Configure them with:

```env
SCOPE_LLM_FORMAT=openai-responses
SCOPE_VISION_FORMAT=openai-responses
SCOPE_IMAGE_FORMAT=openai-images
```

Supported adapters:

| Role | Adapter | Official shape |
| --- | --- | --- |
| Text / optimizer | `openai-chat` | OpenAI Chat Completions, `POST /v1/chat/completions` |
| Text / optimizer | `openai-responses` | OpenAI Responses, `POST /v1/responses` |
| Text / vision | `google-gemini` | Gemini `models/{model}:generateContent` |
| Image | `openai-images` | OpenAI Images, `POST /v1/images/generations` |
| Image | `openai-responses-image` | OpenAI Responses with `image_generation` tool |
| Image | `google-gemini-image` | Gemini native image generation |
| Generic text | `generic-text-json` | Simple JSON wrapper endpoint |
| Generic vision | `generic-vision-json` | Simple JSON wrapper endpoint with data URL images |
| Generic image | `generic-image-json` | Simple JSON image endpoint |
| Legacy image | `openai-images-legacy` | OpenAI-compatible JSON endpoints requiring `response_format` |

## Previous / legacy OpenAI-compatible format

Use this mode for endpoints that follow the older `/v1/images/generations`
JSON style and require an explicit `response_format`.

```env
SCOPE_LLM_FORMAT=openai-chat
SCOPE_VISION_FORMAT=openai-chat
SCOPE_IMAGE_FORMAT=openai-images-legacy
SCOPE_IMAGE_BASE_URL=https://example.com/v1
SCOPE_IMAGE_GENERATIONS_URL=https://example.com/v1/images/generations
SCOPE_RESPONSE_FORMATS=b64_json,url,b64_json,url
SCOPE_IMAGE_N=1
```

Request:

```json
{
  "model": "gpt-image-2",
  "prompt": "compact production prompt",
  "n": 1,
  "response_format": "b64_json"
}
```

Fallback request:

```json
{
  "model": "gpt-image-2",
  "prompt": "compact production prompt",
  "n": 1,
  "response_format": "url"
}
```

Accepted responses:

```json
{"data": [{"b64_json": "..."}]}
```

```json
{"data": [{"url": "https://..."}]}
```

Optional previous-style direct reference image fields are supported only when
the endpoint documents them:

```env
SCOPE_SEND_REFERENCE_IMAGE=1
SCOPE_REFERENCE_IMAGE_FIELD=images
```

This adds one of:

```json
{"images": ["data:image/png;base64,..."]}
```

or:

```json
{"image": "data:image/png;base64,..."}
```

## OpenAI Chat Completions text JSON

```json
{
  "model": "gpt-5.5",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "temperature": 0.25,
  "response_format": {"type": "json_object"}
}
```

## OpenAI Responses text / vision

Text:

```json
{
  "model": "gpt-5.5",
  "input": [
    {"role": "developer", "content": [{"type": "input_text", "text": "..."}]},
    {"role": "user", "content": [{"type": "input_text", "text": "..."}]}
  ],
  "temperature": 0.25
}
```

Vision:

```json
{
  "model": "gpt-5.5",
  "input": [{
    "role": "user",
    "content": [
      {"type": "input_text", "text": "audit this image"},
      {"type": "input_image", "image_url": "data:image/png;base64,..."}
    ]
  }]
}
```

## OpenAI Images generation

Default public path:

```json
{
  "model": "gpt-image-2",
  "prompt": "compact production prompt",
  "size": "1024x1536",
  "quality": "high"
}
```

Expected response:

```json
{"data": [{"b64_json": "..."}]}
```

Do not force `response_format` for current GPT Image models unless you
intentionally select `SCOPE_IMAGE_FORMAT=openai-images-legacy`.

## OpenAI Responses image tool

```json
{
  "model": "gpt-5.5",
  "input": "Generate a cinematic poster...",
  "tools": [{"type": "image_generation"}]
}
```

With reference image:

```json
{
  "model": "gpt-5.5",
  "input": [{
    "role": "user",
    "content": [
      {"type": "input_text", "text": "Use this reference as style guidance..."},
      {"type": "input_image", "image_url": "data:image/png;base64,..."}
    ]
  }],
  "tools": [{"type": "image_generation", "action": "auto"}]
}
```

The image is read from `output[]` entries where `type` is
`image_generation_call` and `result` contains base64 image bytes.

## Gemini generateContent text / vision

Text JSON:

```json
{
  "contents": [{"role": "user", "parts": [{"text": "..."}]}],
  "systemInstruction": {"parts": [{"text": "Return one valid JSON object only."}]},
  "generationConfig": {
    "temperature": 0.25,
    "responseMimeType": "application/json"
  }
}
```

Vision:

```json
{
  "contents": [{
    "role": "user",
    "parts": [
      {"text": "audit this image"},
      {"inlineData": {"mimeType": "image/png", "data": "...base64..."}}
    ]
  }],
  "generationConfig": {"responseMimeType": "application/json"}
}
```

Authentication supports any of:

```env
SCOPE_GOOGLE_API_KEY_AUTH=header  # x-goog-api-key
SCOPE_GOOGLE_API_KEY_AUTH=query   # ?key=...
SCOPE_GOOGLE_API_KEY_AUTH=bearer  # Authorization: Bearer ...
```

## Gemini native image generation

```json
{
  "contents": [{
    "role": "user",
    "parts": [
      {"text": "Create a photorealistic product poster..."}
    ]
  }],
  "generationConfig": {
    "responseModalities": ["TEXT", "IMAGE"]
  }
}
```

With a reference image, add an `inlineData` part. Generated image bytes are read
from `candidates[].content.parts[].inlineData.data`.

## Generic JSON adapters

Use generic adapters when an endpoint is not official OpenAI/Gemini but accepts
simple JSON. They are intentionally small and predictable; if a provider needs a
very different schema, add a local wrapper endpoint that translates this shape.

### Generic text

```env
SCOPE_LLM_FORMAT=generic-text-json
SCOPE_LLM_ENDPOINT_URL=https://example.com/text
SCOPE_LLM_PAYLOAD_STYLE=both
SCOPE_LLM_AUTH_MODE=bearer
```

Payload style `both`:

```json
{
  "model": "custom-llm",
  "system": "...",
  "prompt": "...",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "temperature": 0.25,
  "json": true,
  "response_format": {"type": "json_object"}
}
```

Set `SCOPE_LLM_PAYLOAD_STYLE=messages` or `prompt` to send only that shape.

Accepted text response fields include:

```text
choices[].message.content
text
content
output_text
response
result
message
output[]
```

### Generic vision

```env
SCOPE_VISION_FORMAT=generic-vision-json
SCOPE_VISION_ENDPOINT_URL=https://example.com/vision
SCOPE_VISION_PAYLOAD_STYLE=both
```

Payload adds data URL reference images:

```json
{
  "model": "custom-vision",
  "system": "...",
  "prompt": "audit this image",
  "messages": [{"role": "user", "content": "audit this image"}],
  "images": ["data:image/png;base64,..."],
  "image": "data:image/png;base64,...",
  "json": true
}
```

### Generic image

```env
SCOPE_IMAGE_FORMAT=generic-image-json
SCOPE_IMAGE_ENDPOINT_URL=https://example.com/image
SCOPE_IMAGE_RESPONSE_FORMAT=b64_json
```

Payload:

```json
{
  "model": "custom-image",
  "prompt": "compact production prompt",
  "n": 1,
  "size": "1024x1536",
  "quality": "high",
  "response_format": "b64_json"
}
```

With a reference image, the runner adds:

```json
{
  "images": ["data:image/png;base64,..."],
  "image": "data:image/png;base64,..."
}
```

Accepted image response fields include:

```text
data[].b64_json
data[].url
images[].base64
images[].url
b64_json
base64
image_base64
image
url
image_url
output[].result
```

### Generic auth

```env
SCOPE_GENERIC_AUTH_MODE=bearer
SCOPE_GENERIC_AUTH_MODE=api-key
SCOPE_GENERIC_AUTH_MODE=header:X-Custom-Key
SCOPE_GENERIC_AUTH_MODE=query
SCOPE_GENERIC_AUTH_MODE=none
```

Optional overrides:

```env
SCOPE_GENERIC_AUTH_HEADER=X-API-Key
SCOPE_GENERIC_API_KEY_QUERY_PARAM=api_key
SCOPE_LLM_AUTH_MODE=bearer
SCOPE_VISION_AUTH_MODE=header:X-API-Key
SCOPE_IMAGE_AUTH_MODE=query
```

## Reference images

Default behavior is still robust and vendor-neutral:

```text
reference image -> vision model brief -> prompt injection -> image generation
```

For direct reference-image calls:

- Use `SCOPE_IMAGE_FORMAT=openai-responses-image` for OpenAI Responses image tool.
- Use `SCOPE_IMAGE_FORMAT=google-gemini-image` for Gemini native image generation.
- The OpenAI Images `/v1/images/edits` multipart reference workflow is an
  official API shape, but not the default JSON runner path.

## Provider config

Copy `references/provider-config.example.json` to a local config, replace
placeholder URLs/env names, and validate:

```bash
python scripts/validate_provider_config.py references/provider-config.example.json
python scripts/render_provider_payload.py --config references/provider-config.example.json --role image_generator --prompt "a cat"
```

Keep real secrets in environment variables only.
