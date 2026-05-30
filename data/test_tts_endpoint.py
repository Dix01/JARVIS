"""Quick test: verify the TTS endpoint works end-to-end."""
import asyncio
import httpx

async def test():
    # Start the server briefly just to test the TTS route
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "http://127.0.0.1:7341/api/tts",
            json={"text": "Online sir, systems nominal."},
        )
        print(f"Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('content-type', 'unknown')}")
        print(f"Audio size: {len(resp.content)} bytes")
        if resp.status_code == 200 and len(resp.content) > 100:
            print("TTS ENDPOINT WORKS!")
        else:
            print(f"TTS FAILED: {resp.text[:200]}")

asyncio.run(test())
