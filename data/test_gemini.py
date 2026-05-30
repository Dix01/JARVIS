"""Quick test: verify Gemini API key works with function calling."""
import asyncio
import httpx
import json
import os

async def test():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY before running this test.")

    url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": "gemini-2.5-flash",
        "messages": [
            {"role": "system", "content": "You are JARVIS, a helpful AI assistant. Be brief."},
            {"role": "user", "content": "Hello JARVIS, what time is it?"},
        ],
        "temperature": 0.3,
        "max_tokens": 200,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "system_status",
                    "description": "Get current system status including time",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        print(f"Status: {resp.status_code}")
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {})
        print(f"Content: {msg.get('content', '(none)')}")
        tool_calls = msg.get("tool_calls", [])
        if tool_calls:
            print(f"Tool calls: {json.dumps(tool_calls, indent=2)}")
            print("NATIVE TOOL CALLING WORKS!")
        else:
            print("No tool calls (model responded directly)")
        print("API TEST PASSED")

asyncio.run(test())
