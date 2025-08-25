import re, io
from openai import OpenAI

def tts_mp3(script_text: str, model: str, voice: str) -> bytes:
    client = OpenAI()
    cleaned = re.sub(r"\[break\s*[0-9.]+s\]", "\n\n", script_text or "")
    with client.audio.speech.with_streaming_response.create(
        model=model, voice=voice, input=cleaned
    ) as resp:
        buf = io.BytesIO()
        for chunk in resp.iter_bytes():
            buf.write(chunk)
    return buf.getvalue()
