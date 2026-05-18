import os

from openai import OpenAI


def main() -> int:
    api_key = (
        os.environ.get("MOARK_API_KEY")
        or os.environ.get("LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    )
    api_key = api_key.strip().strip("`").strip()
    if api_key.lower().startswith("bearer "):
        api_key = api_key.split(" ", 1)[1].strip()

    base_url = (
        os.environ.get("MOARK_BASE_URL")
        or os.environ.get("LLM_BASE_URL")
        or "https://api.moark.com/v1"
    ).strip()
    model = (os.environ.get("MOARK_MODEL") or os.environ.get("LLM_MODEL") or "MiniMax-M2.7").strip()

    print("Using base_url:", base_url)
    print("Using model:", model)

    if not api_key.strip():
        raise SystemExit("缺少 API key：请设置环境变量 MOARK_API_KEY（或 LLM_API_KEY/OPENAI_API_KEY）")

    client = OpenAI(
        base_url=base_url,
        api_key=api_key,
        default_headers={"X-Failover-Enabled": "true"},
    )

    response = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": "你是通过 OpenAI 兼容接口提供服务的助手。禁止提 Claude/Anthropic。只解释 moark 的 chat.completions 调用与参数。",
            },
            {
                "role": "user",
                "content": f"当前请求 base_url={base_url}，model={model}。请说明：1) 这个接口怎么调用 2) 关键参数含义 3) 如何切换模型。用中文列5条。",
            },
        ],
        model=model,
        stream=True,
        max_tokens=1024,
        temperature=0.7,
        top_p=0.7,
        extra_body={"top_k": 50},
        frequency_penalty=1,
    )

    full = ""
    printed_response_model = False
    for chunk in response:
        if not printed_response_model:
            m = getattr(chunk, "model", None)
            if isinstance(m, str) and m.strip():
                print("Response model:", m.strip())
                printed_response_model = True
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            full += reasoning
            print(reasoning, end="", flush=True)
            continue
        content = getattr(delta, "content", None)
        if content:
            full += content
            print(content, end="", flush=True)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
