# chengyu/cover_ai.py
import io, re, base64
from typing import Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from openai import OpenAI

# Pull runtime settings (with safe fallbacks if someone imports this module alone)
try:
    from chengyu.config import settings
    _IMAGE_MODEL   = getattr(settings, "IMAGE_MODEL", "gpt-image-1")
    _IMAGE_SIZE    = getattr(settings, "IMAGE_SIZE", "1024x1024")
    _CN_BRUSH_FONT = getattr(settings, "CN_BRUSH_FONT", "assets/fonts/PingFangSC.ttf")
    _SHOW_NAME     = getattr(settings, "SHOW_NAME", "Chengyu Bites")
except Exception:
    _IMAGE_MODEL, _IMAGE_SIZE = "gpt-image-1", "1024x1024"
    _CN_BRUSH_FONT, _SHOW_NAME = "assets/fonts/PingFangSC.ttf", "Chengyu Bites"

# -------------------- helpers: size, fonts, text --------------------

def _normalize_size(size) -> str:
    """
    Accepts: 'auto', '1024x1024', '1024x1536', '1536x1024'
    Also tolerates legacy ints/strings -> maps to '1024x1024'.
    """
    if isinstance(size, int):
        return "1024x1024"
    if isinstance(size, str):
        s = size.strip().lower()
        if s in {"auto", "1024x1024", "1024x1536", "1536x1024"}:
            return s
        if s.isdigit():
            return "1024x1024"
    return "1024x1024"

def _pick_font(paths, size: int) -> ImageFont.FreeTypeFont:
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()

def _font_cn(size: int) -> ImageFont.FreeTypeFont:
    # 1) your brush font
    f = _pick_font([_CN_BRUSH_FONT], size)
    if f is not ImageFont.load_default():
        return f
    # 2) repo fallbacks then system fallbacks
    return _pick_font([
        "assets/fonts/LongCang-Regular.ttf",
        "assets/fonts/ZhiMangXing-Regular.ttf",
        "/System/Library/Fonts/STKaiti.ttf",
        "/System/Library/Fonts/Songti.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ], size)

def _font_latn(size: int) -> ImageFont.FreeTypeFont:
    return _pick_font([
        "/System/Library/Fonts/SFNS.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ], size)

def _stroke_text(draw: ImageDraw.ImageDraw, xy: Tuple[int,int], text: str,
                 font: ImageFont.FreeTypeFont, fill=(15,15,15),
                 stroke_w=8, stroke_fill="white", anchor="mm"):
    draw.text(xy, text, font=font, fill=fill,
              stroke_width=stroke_w, stroke_fill=stroke_fill, anchor=anchor)

def _draw_brush_text(canvas: Image.Image, xy: Tuple[int,int], text: str,
                     font: ImageFont.FreeTypeFont, ink=(15,15,15),
                     stroke_w=20, stroke_fill="white", anchor="mm"):
    """
    Brush-look text:
      1) soft blurred ink underlay (organic bleed)
      2) crisp main text with white stroke for readability
    """
    W, H = canvas.size
    under = Image.new("RGBA", (W, H), (0,0,0,0))
    du = ImageDraw.Draw(under)
    du.text(xy, text, font=font, fill=(0,0,0,220), anchor=anchor)
    under = under.filter(ImageFilter.GaussianBlur(1.4))
    canvas.alpha_composite(under)

    d = ImageDraw.Draw(canvas)
    d.text(xy, text, font=font, fill=ink,
           stroke_width=stroke_w, stroke_fill=stroke_fill, anchor=anchor)

# -------------------- story extraction --------------------

def _extract_story(script: str) -> str:
    """Grab origin story-ish text from the script to steer the background."""
    if not script:
        return ""
    m = re.search(r"Here.?s the story behind it:\s*(.*)", script, flags=re.I|re.S)
    block = m.group(1).strip() if m else script
    block = re.sub(r"\[break\s*\d+(\.\d+)?s\]", " ", block)
    block = re.sub(r"\s+", " ", block).strip()
    return block[:700]

# -------------------- AI background --------------------

def _ai_background(chengyu: str, pinyin: str, gloss: str, story: str,
                   model: str = None, size: str = None) -> Image.Image:
    """
    Generate a square ancient-ink illustration with NO text.
    """
    client = OpenAI()
    model = model or _IMAGE_MODEL
    size  = _normalize_size(size or _IMAGE_SIZE)

    prompt = f"""
Ancient Chinese ink painting style, square composition.
Chengyu: "{chengyu}" (pinyin: {pinyin})
Meaning: {gloss}
Story details: {story}

Art direction:
- Black ink on warm rice-paper tone; visible fibers and brushwork.
- Evocative scene that reflects the story; traditional setting/props.
- Leave a calmer, low-contrast vertical band in the center for overlaid text.
- No text or calligraphy; no borders, frames, or logos; no watermarks.
- Traditional, refined, balanced composition.
"""
    res = client.images.generate(
        model=model,
        prompt=prompt,
        size=size,
        quality="high"
    )
    b64 = res.data[0].b64_json
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")

# -------------------- red seal --------------------

def _red_seal(canvas: Image.Image, text="成语", pos="tr", margin=110):
    """
    Add a small red stamp. pos: 'tr' (top-right), 'tl', 'br', 'bl'
    """
    W, H = canvas.size
    seal_w, seal_h = 380, 420
    seal = Image.new("RGBA", (seal_w, seal_h), (168,22,22,255))
    ds = ImageDraw.Draw(seal)
    # inner border
    ds.rectangle((8,8,seal_w-8,seal_h-8), outline=(255,232,220,255), width=8)
    f = _font_cn(200)
    tw, th = ds.textbbox((0,0), text, font=f)[2:]
    ds.text(((seal_w-tw)//2, (seal_h-th)//2-6), text, font=f, fill=(255,245,240,255))
    seal = seal.filter(ImageFilter.GaussianBlur(0.4))

    if pos == "tr":
        xy = (W - seal_w - margin, margin)
    elif pos == "tl":
        xy = (margin, margin)
    elif pos == "br":
        xy = (W - seal_w - margin, H - seal_h - margin)
    else:
        xy = (margin, H - seal_h - margin)

    canvas.alpha_composite(seal, xy)

# -------------------- main: build full cover --------------------

def draw_cover_png_story(*,
    chengyu: str,
    pinyin: str,
    english: str,
    script: str,
    show_mark: str = None,
    model: str = None,
    size: str = None,
    out_size: int = 3000,
    seal_text: str = "成语",
    seal_pos: str = "tr"
) -> bytes:
    """
    Build a story-driven cover (PNG bytes):
      1) AI 'ink painting' background (no text)
      2) Central soft band for legibility
      3) Brush idiom (ink-bleed + white stroke), pinyin below, English at bottom
      4) Small red seal in the corner
    """
    show_mark = show_mark or _SHOW_NAME
    story = _extract_story(script)

    # 1) background (with graceful fallback)
    try:
        bg = _ai_background(chengyu, pinyin, english, story, model=model, size=size)
    except Exception:
        # fallback parchment if image API fails
        bg = Image.new("RGBA", (1024, 1024), "#eee6d4")
        g = Image.new("L", (1024, 1024), 0); d = ImageDraw.Draw(g)
        d.ellipse((60,60,964,964), fill=255)
        g = g.filter(ImageFilter.GaussianBlur(120))
        bg = Image.composite(bg, Image.new("RGBA",(1024,1024),"#f6f0e3"), g)

    # upscale to final
    if bg.size != (out_size, out_size):
        bg = bg.resize((out_size, out_size), Image.LANCZOS)
    W = H = out_size

    # 2) subtle central band for legibility
    band = Image.new("RGBA", (W, H), (255,255,255,0))
    db = ImageDraw.Draw(band)
    margin_x = int(W * 0.10)
    db.rectangle((margin_x, int(H*0.24), W - margin_x, int(H*0.80)), fill=(255,255,255,68))
    band = band.filter(ImageFilter.GaussianBlur(8))
    bg.alpha_composite(band, (0,0))

    # Prepare canvas for text overlays
    canvas = Image.new("RGBA", (W, H), (0,0,0,0))
    d = ImageDraw.Draw(canvas)

    # 3) typography
    f_big   = _font_cn(600)     # idiom (brush)
    f_mid   = _font_latn(190)   # pinyin
    f_small = _font_latn(140)   # english
    f_mark  = _font_latn(84)    # brand

    ink = (15,15,15)
    cx, cy = W//2, H//2 - 140

    # Idiom (center) with brush font + bleed + white stroke
    _draw_brush_text(canvas, (cx, cy), chengyu, f_big, ink=ink, stroke_w=22)

    # Pinyin (below) — clean sans with white stroke
    _stroke_text(d, (cx, cy + 460), pinyin, f_mid, fill=ink, stroke_w=12)

    # English (bottom, wrapped roughly to ~28 chars)
    def _wrap_en(text: str, max_chars=28) -> str:
        out, line = [], ""
        for w in (text or "").split():
            if len(line) + len(w) + 1 > max_chars:
                out.append(line); line = w
            else:
                line += (" " if line else "") + w
        if line: out.append(line)
        return "\n".join(out[:3])
    eng = _wrap_en(english, 28)

    d.multiline_text((cx, H - 420), eng, font=f_small, fill=ink,
                     stroke_width=8, stroke_fill="white",
                     anchor="mm", align="center", spacing=8)

    # Brand mark (top-left, subtle)
    d.text((140, 140), show_mark, font=f_mark, fill=(60,60,60),
           stroke_width=6, stroke_fill="white", anchor="ls")

    # 4) red seal
    _red_seal(canvas, text=seal_text, pos=seal_pos, margin=110)

    # composite
    out = Image.alpha_composite(bg, canvas)
    buf = io.BytesIO()
    out.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()
