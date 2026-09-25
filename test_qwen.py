import os
from openai import OpenAI

api_key = os.environ.get("QWEN_API_KEY", "")
base_url = os.environ.get("QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
model = os.environ.get("QWEN_MODEL", "qwen-plus")

print(f"Model: {model}")
print(f"Base URL: {base_url}")
print(f"API Key set: {bool(api_key)}")

import httpx
client = OpenAI(api_key=api_key, base_url=base_url, timeout=30.0)
try:
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Say hello in one word."}],
        max_tokens=10,
    )
    print("Response:", response.choices[0].message.content)
    print("Qwen model is working!")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
