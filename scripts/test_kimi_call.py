"""Quick test: single Claude Agent SDK call routed to Moonshot/Kimi API.

Proves that swapping ANTHROPIC_BASE_URL + ANTHROPIC_API_KEY lets the SDK
talk to any OpenAI-compatible endpoint (Ollama, Kimi, etc.)

Run ON LAPTOP-SERVER (where secrets live):
    source ~/.secrets/claw.env
    ANTHROPIC_BASE_URL="$MOONSHOT_API_BASE" \
    ANTHROPIC_API_KEY="$MOONSHOT_API_KEY" \
    python scripts/test_kimi_call.py
"""

import asyncio
import os
import sys


async def main():
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not base_url:
        print("ERROR: ANTHROPIC_BASE_URL not set. Set it to Moonshot endpoint.")
        sys.exit(1)
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set. Set it to Moonshot API key.")
        sys.exit(1)

    print(f"Target endpoint: {base_url}")
    print(f"API key present: {'yes' if api_key else 'no'} (len={len(api_key)})")
    print()

    # Try direct HTTP call first (no SDK) to verify the endpoint works
    import json
    import urllib.request

    req_body = json.dumps(
        {
            "model": "moonshot-v1-8k",
            "messages": [{"role": "user", "content": "Say hello in one sentence."}],
            "max_tokens": 50,
        }
    ).encode()

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=req_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    print("--- Direct API call (no SDK) ---")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            content = data["choices"][0]["message"]["content"]
            model_used = data.get("model", "unknown")
            print(f"Model: {model_used}")
            print(f"Response: {content}")
            print("Direct call: SUCCESS")
    except Exception as e:
        print(f"Direct call: FAILED — {e}")
        # Still try SDK call below

    print()
    print("--- SDK call (ClaudeSDKClient) ---")
    try:
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        options = ClaudeAgentOptions(
            system_prompt="You are a helpful assistant. Respond briefly.",
            permission_mode="bypassPermissions",
        )

        async with ClaudeSDKClient(options=options) as client:
            await client.query("What model are you? Reply in one sentence.")
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(f"SDK Response: {block.text}")
        print("SDK call: SUCCESS")
    except Exception as e:
        print(f"SDK call: FAILED — {e}")


if __name__ == "__main__":
    asyncio.run(main())
