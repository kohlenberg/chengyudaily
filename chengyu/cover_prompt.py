# chengyu/cover_prompt.py
import io, base64
from openai import OpenAI
from PIL import Image

SUPPORTED_SIZES = {"1024x1024", "1024x1536", "1536x1024", "auto"}
def _norm_size(size):
    return size if isinstance(size, str) and size in SUPPORTED_SIZES else "1024x1024"

def generate_cover_direct(*, chengyu: str, pinyin: str, english: str,
                          story: str = "", model: str = "gpt-image-1",
                          size: str = "1024x1024", out_size: int = 3000) -> bytes:
    client = OpenAI()
    size = _norm_size(size)
    prompt = f"""
Square podcast cover in traditional Chinese ink painting (shui-mo / sumi-e).
Idiom: {chengyu}
Pinyin: {pinyin}
English: {english}
Story cues: {story or 'traditional setting; culturally authentic.'}

Layout:
- Top center: EXACT characters {chengyu} — hand-brushed calligraphy, black ink, with a soft white outline for legibility.
- Center: EXACT pinyin {pinyin} — clean Latin text with white outline.
- Bottom center: EXACT English "{english}" — 1–2 lines max, white outline.
- Small red seal near top-right.

Background:
- Ancient ink painting scene that reflects the idiom; warm rice-paper texture.
- Keep a calmer vertical band through center for readable text.
- No extra text, no watermarks, no borders/frames.
"""
    res = client.images.generate(model=model, prompt=prompt, size=size, quality="medium")
    img = Image.open(io.BytesIO(base64.b64decode(res.data[0].b64_json))).convert("RGB")
    if img.size != (out_size, out_size):
        img = img.resize((out_size, out_size), Image.LANCZOS)
    buf = io.BytesIO(); img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
