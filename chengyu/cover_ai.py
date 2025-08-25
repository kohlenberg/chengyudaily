# chengyu/cover_ai.py
import io, re, math, random, base64
from typing import Optional
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from openai import OpenAI

# ---------- fonts & text helpers (reuse-friendly) ----------
def _pick_font(paths, size):
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()

def _font_cn(size):
    return _pick_font([
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STKaiti.ttf",
        "/System/Library/Fonts/Songti.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ], size)

def _font_latn(size):
    return _pick_font([
        "/System/Library/Fonts/SFNS.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ], size)

def _stroke_text(draw, xy, text, font, fill, stroke_w=8, stroke_fill="white", anchor="mm"):
    draw.text(xy, text, font=font, fill=fill,
              stroke_width=stroke_w, stroke_fill=stroke_fill, anchor=anchor)

def _extract_story(script: str) -> str:
    """Grab the origin story paragraph to inform the background prompt."""
    if not script:
        return ""
    # Look for "Here’s the story behind it:" and take the next ~5 sentences.
    m = re.search(r"Here.?s the story behind it:\s*(.*)", script, flags=re.I|re.S)
    if m:
        block = m.group(1).strip()
    else:
        block = script
    # Keep it concise
    block = re.sub(r"\[break\s*\d+(\.\d+)?s\]", " ", block)
    block = re.sub(r"\s+", " ", block).strip()
    return block[:600]

# ---------- AI background ----------
def _ai_background(chengyu: str, pinyin: str, gloss: str, story: str,
                   model: str = "gpt-image-1", size: int = 2048) -> Image.Image:
    """
    Generate a square, ancient-ink illustration inspired by the story.
    We ask for 'no text' so we can overlay clean type ourselves.
    """
    client = OpenAI()
    prompt = f"""
Ancient Chinese ink painting style, square composition.
Chengyu: "{chengyu}" (pinyin: {pinyin})
Theme/meaning: {gloss}
Story details: {story}

Art direction:
- Black ink on warm fiber/rice-paper tone; subtle brushwork and wash.
- Evocative scene that reflects the story (no modern props).
- Leave a calmer, low-contrast area in the central vertical band for typography.
- No text, no calligraphy, no watermarks, no frames, no borders, no logos.
- High detail, gentle contrast, organic fibers visible, traditional aesthetics.
"""
    res = client.images.generate(
        model=model,
        prompt=prompt,
        size=f"{size}x{size}",
        quality="high"
    )
    b64 = res.data[0].b64_json
    img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")
    return img

# ---------- compositing ----------
def draw_cover_png_story(*,
    chengyu: str,
    pinyin: str,
    english: str,
    script: str,
    show_mark: str = "Chengyu Bites",
    model: str = "gpt-image-1",
    size: int = 2048,
    out_size: int = 3000
) -> bytes:
    """
    Full pipeline:
      1) AI background (ink painting) guided by story
      2) Overlay stroked text: idiom (center), pinyin (below), English (bottom)
      3) Optional vignette to help legibility
    Returns PNG bytes (3000x3000).
    """
    story = _extract_story(script)
    try:
        bg = _ai_background(chengyu, pinyin, english, story, model=model, size=size)
    except Exception as e:
        # Fallback: gentle parchment gradient if image API fails
        bg = Image.new("RGBA", (size, size), "#eee6d4")
        g = Image.new("L", (size, size), 0); d = ImageDraw.Draw(g)
        d.ellipse((int(size*0.05), int(size*0.05), int(size*0.95), int(size*0.95)), fill=255)
        g = g.filter(ImageFilter.GaussianBlur(size//10))
        bg = Image.composite(bg, Image.new("RGBA",(size,size),"#f6f0e3"), g)

    # upscale/canvas to final
    if size != out_size:
        bg = bg.resize((out_size, out_size), Image.LANCZOS)
    W = H = out_size
    canvas = Image.new("RGBA", (W, H), (0,0,0,0))
    d = ImageDraw.Draw(canvas)

    # Subtle central band for legibility (transparent white wash)
    band = Image.new("RGBA", (W, H), (255,255,255,0))
    db = ImageDraw.Draw(band)
    margin_x = int(W*0.10)
    db.rectangle((margin_x, int(H*0.25), W-margin_x, int(H*0.80)), fill=(255,255,255,72))
    band = band.filter(ImageFilter.GaussianBlur(8))
    bg.alpha_composite(band, (0,0))

    # Fonts
    f_big   = _font_cn(560)     # idiom
    f_mid   = _font_latn(190)   # pinyin
    f_small = _font_latn(140)   # english
    f_mark  = _font_latn(84)    # brand

    ink = (15,15,15)
    cx, cy = W//2, H//2 - 140

    # Idiom (center)
    _stroke_text(d, (cx, cy), chengyu, f_big, fill=ink, stroke_w=18)

    # Pinyin (below)
    _stroke_text(d, (cx, cy + 460), pinyin, f_mid, fill=ink, stroke_w=10)

    # English (bottom, wrapped)
    def wrap_en(text, max_chars=30):
        out, line = [], ""
        for w in text.split():
            if len(line)+len(w)+1 > max_chars:
                out.append(line); line = w
            else:
                line += (" " if line else "") + w
        if line: out.append(line)
        return "\n".join(out[:3])

    eng = wrap_en(english, 28)
    d.multiline_text((cx, H-420), eng, font=f_small, fill=ink,
                     stroke_width=8, stroke_fill="white", anchor="mm", align="center", spacing=8)

    # Brand mark (top-left, subtle)
    d.text((140,140), show_mark, font=f_mark, fill=(60,60,60),
           stroke_width=6, stroke_fill="white", anchor="ls")

    out = Image.alpha_composite(bg, canvas)
    buf = io.BytesIO()
    out.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()
