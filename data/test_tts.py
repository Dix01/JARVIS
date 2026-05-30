import asyncio
import edge_tts

async def test():
    c = edge_tts.Communicate("Test audio from JARVIS", voice="en-GB-RyanNeural", rate="-8%", pitch="-10Hz")
    data = b""
    async for chunk in c.stream():
        if chunk["type"] == "audio":
            data += chunk["data"]
    print(f"Audio generated: {len(data)} bytes")
    if len(data) > 0:
        print("TTS OK - edge_tts is working")
    else:
        print("TTS FAIL - no audio data generated")

asyncio.run(test())
