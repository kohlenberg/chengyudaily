# chengyu/cover_hybrid.py
# Hybrid cover generator:
# - Image model paints: background + EXACT Chinese characters (brush calligraphy) + red seal
# - Pillow overlays: pinyin (Latin, with diacritics) + English meaning (auto-fitted, brushy styling)
# - Exports a compact 1500x1500 cover (JPEG by default; PNG supported)

import io
import re
import base64
from typing import Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from openai import OpenAI

# ---------------------- size & font helpers ----------------------

SUPPORTED_SIZES = {"1024x1024", "1024x1536", "1536x1024", "auto"}

def _norm_size(size: str) -> str:
    s = (size or "1024x1024").lower()
    return s if s in SUPPORTED_SIZES else "1024x1024"

def _pick_font(paths, size: int) -> ImageFont.FreeTypeFont:
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()

def _font_latn(size: int) -> ImageFont.FreeTypeFont:
    # General Latin fallback (used if nothing else available)
    return _pick_font([
        "assets/fonts/EBGaramond-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/Library/Fonts/Times New Roman.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ], size)

def _font_pinyin(size: int) -> ImageFont.FreeTypeFont:
    # Prefer brushy Latin fonts; fall back to Gentium Plus for diacritics.
    return _pick_font([
        "assets/fonts/Kalam-Regular.ttf",            # brush-like handwriting
        "assets/fonts/PatrickHand-Regular.ttf",      # handwriting style
        "assets/fonts/GentiumPlus-Regular.ttf",      # excellent tone marks
        "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/Library/Fonts/Times New Roman.ttf",
    ], size)

def _font_english(size: int) -> ImageFont.FreeTypeFont:
    # English line — prefer brushy handwriting, else warm serif
    return _pick_font([
        "assets/fonts/Kalam-Regular.ttf",
        "assets/fonts/PatrickHand-Regular.ttf",
        "assets/fonts/EBGaramond-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/Library/Fonts/Times New Roman.ttf",
    ], size)

# ---------------------- text style helpers ----------------------

def _sanitize_english(s: str) -> str:
    """Remove stray accent marks/quotes that sometimes sneak into text fields elsewhere."""
    if not s:
        return ""
    trans = {
        0x00B4: ord("'"),  # ´ -> '
        0x2018: ord("'"),  # ‘ -> '
        0x2019: ord("'"),  # ’ -> '
        0x201C: ord('"'),  # “ -> "
        0x201D: ord('"'),  # ” -> "
        0x02BC: ord("'"),  # modifier apostrophe -> '
        0x02C8: ord("'"),  # ˈ -> '
    }
    s = s.translate(trans)
    return re.sub(r"\s+", " ", s).strip()

def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, stroke_w: int = 0) -> Tuple[int, int]:
    """Measure multiline text (max width + total height) using textbbox."""
    lines = text.split("\n")
    w = h = 0
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_w)
        lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        w = max(w, lw)
        h += lh + (8 if i < len(lines) - 1 else 0)
    return w, h

def _fit_single_line(draw, text, font_picker, max_width, start=176, min_size=96, stroke_ratio=0.06):
    """Downscale font size until a single line fits within max_width."""
    size = start
    while size >= min_size:
        f = font_picker(size)
        sw = max(2, int(size * stroke_ratio))
        w, _ = _measure(draw, text, f, stroke_w=sw)
        if w <= max_width:
            return f, sw
        size -= 6
    f = font_picker(min_size)
    sw = max(2, int(min_size * stroke_ratio))
    return f, sw

def _wrap_to_width(draw, text, font_picker, max_width, max_lines=2, start=140, min_size=90, stroke_ratio=0.05):
    """Word-wrap to <= max_lines and downscale font until all lines fit width."""
    words = (text or "").split()
    size = start
    while size >= min_size:
        f = font_picker(size)
        sw = max(2, int(size * stroke_ratio))
        lines, line = [], ""
        for w in words:
            test = (line + " " + w).strip()
            tw, _ = _measure(draw, test, f, stroke_w=sw)
            if tw <= max_width or not line:
                line = test
            else:
                lines.append(line)
                line = w
                if len(lines) >= max_lines:
                    lines = None
                    break
        if lines is not None:
            if line:
                lines.append(line)
            if all(_measure(draw, ln, f, stroke_w=sw)[0] <= max_width for ln in lines):
                return "\n".join(lines), f, sw
        size -= 6

    # Fallback: do a best-effort wrap at min_size
    f = font_picker(min_size)
    sw = max(2, int(min_size * stroke_ratio))
    lines, line = [], ""
    for w in words:
        test = (line + " " + w).strip()
        tw, _ = _measure(ImageDraw.Draw(Image.new("RGB", (10, 10))), test, f, stroke_w=sw)
        if tw <= max_width or not line:
            line = test
        else:
            lines.append(line)
            line = w
            if len(lines) >= max_lines:
                break
    if line and len(lines) < max_lines:
        lines.append(line)
    return "\n".join(lines[:max_lines]), f, sw

def _draw_brushy_soft_text(canvas, xy, text, font,
                           ink=(44,38,32),            # warm ink
                           stroke_w=8,
                           stroke_fill=(246,242,235), # paper-ish stroke
                           anchor="mm",
                           bleed_blur=1.4,
                           bleed_alpha=210,
                           jitter=1):
    """
    Softer 'ink on paper' look:
      - slightly blurred under-ink layer (bleed)
      - 1-2 jittered passes for rougher edges
      - stroked main text with paper-toned outline
    """
    W, H = canvas.size
    cx, cy = xy

    # under-ink bleed
    under = Image.new("RGBA", (W, H), (0,0,0,0))
    du = ImageDraw.Draw(under)
    du.text((cx, cy), text, font=font, fill=(0,0,0,bleed_alpha), anchor=anchor)
    under = under.filter(ImageFilter.GaussianBlur(bleed_blur))
    canvas.alpha_composite(under)

    # jittered mid-pass (dark, thin) to get rough edge
    mid = Image.new("RGBA", (W, H), (0,0,0,0))
    dm = ImageDraw.Draw(mid)
    offsets = [(-jitter, 0), (jitter, 0)]
    for dx, dy in offsets:
        dm.text((cx+dx, cy+dy), text, font=font, fill=(20,18,16,120), anchor=anchor)
    canvas.alpha_composite(mid)

    # main pass with stroke
    d = ImageDraw.Draw(canvas)
    d.text((cx, cy), text, font=font, fill=ink,
           stroke_width=stroke_w, stroke_fill=stroke_fill, anchor=anchor)

# ---------------------- image background with characters ----------------------

def _ai_bg_with_chars(chengyu: str, pinyin: str, english: str, story: str,
                      model: str, size: str, quality: str = "medium") -> Image.Image:
    """
    Ask the image model to paint: ancient ink background + EXACT Chinese characters.
    No Latin letters/pinyin/English in the image. Include a small red seal.
    """
    client = OpenAI()
    size = _norm_size(size)
    prompt = f"""
Square podcast cover in traditional Chinese ink painting (shui-mo / sumi-e).
Paint an evocative scene that reflects this idiom.

Idiom (characters to paint): {chengyu}
Pinyin: {pinyin}
English meaning: {english}
Story cues: {story or 'traditional setting; culturally authentic.'}

Layout & rules (strict):
- Paint the **exact** Chinese characters {chengyu} as large hand-brushed calligraphy,
  centered near the upper-middle (black ink), with natural brush texture.
- Add a small red seal (印章) near the top-right.
- DO NOT include any Latin letters or English at all. No pinyin. No extra Chinese text beyond {chengyu}.
- Warm rice-paper texture; visible fibers and ink washes.
- Leave a calmer, low-contrast vertical band through the center so additional text can be added below later.
- No borders, frames, or watermarks.
"""
    res = client.images.generate(model=model, prompt=prompt, size=size, quality=quality)
    return Image.open(io.BytesIO(base64.b64decode(res.data[0].b64_json))).convert("RGBA")

# ---------------------- main API ----------------------

def generate_cover_hybrid(
    *,
    chengyu: str,
    pinyin: str,
    english: str,
    story: str = "",
    model: str = "gpt-image-1",
    size: str = "1024x1024",
    quality: str = "medium",      # "low" | "medium" | "high"
    out_size: int = 1500,         # final square
    out_format: str = "JPEG",     # "JPEG" (small) or "PNG"
    jpeg_quality: int = 82,       # file size sweet spot
    jpeg_subsampling: int = 2,    # 4:2:0
    progressive: bool = True,
    # positioning (relative to height)
    pinyin_y: float = 0.50,       # << higher under the characters (was 0.56)
    english_y: float = 0.78       # << below the pinyin
) -> bytes:
    """
    Model paints background + CHINESE characters; we overlay pinyin + English.
    - Pinyin sits directly beneath the painted characters (higher on the page).
    - Pinyin auto-scales to one line; English wraps/scales to <=2 lines.
    - No brand text added.
    """

    # 1) Background (with characters)
    img = _ai_bg_with_chars(chengyu, pinyin, english, story, model=model, size=size, quality=quality)
    if img.size != (out_size, out_size):
        img = img.resize((out_size, out_size), Image.LANCZOS)
    W = H = out_size

    # 2) Subtle central band for readability of overlays (lifted a bit higher)
    band = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    db = ImageDraw.Draw(band)
    side_pad = int(W * 0.10)
    db.rectangle((side_pad, int(H * 0.42), W - side_pad, int(H * 0.90)), fill=(255, 255, 255, 60))
    band = band.filter(ImageFilter.GaussianBlur(7))
    img.alpha_composite(band, (0, 0))

    # 3) Overlay pinyin + English (auto-fit, brushy soft style)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)

    f_py_picker = _font_pinyin
    f_en_picker = _font_english

    # Palette
    ink   = (44, 38, 32)    # warm ink (not pure black)
    paper = (246, 242, 235) # paper-ish stroke (not pure white)
    cx    = W // 2
    max_w = W - 2 * (side_pad + 20)  # wiggle room for stroke

    # Pinyin: single line, auto-scale; higher under characters
    pinyin = (pinyin or "").strip()
    f_py, sw_py = _fit_single_line(d, pinyin, f_py_picker, max_width=max_w, start=176, min_size=96, stroke_ratio=0.06)
    _draw_brushy_soft_text(
        canvas,
        (cx, int(H * pinyin_y)),   # default 0.50; try 0.48 for even higher
        pinyin,
        f_py,
        ink=ink,
        stroke_w=sw_py,
        stroke_fill=paper,
        bleed_blur=1.4,
        bleed_alpha=210,
        jitter=1
    )

    # English: sanitize → wrap to <=2 lines, auto-scale to width; under pinyin
    en_text = _sanitize_english(english)
    en_wrapped, f_en, sw_en = _wrap_to_width(d, en_text, f_en_picker, max_width=max_w, max_lines=2, start=140, min_size=90, stroke_ratio=0.05)

    _draw_brushy_soft_text(
        canvas,
        (cx, int(H * english_y)),  # default 0.78
        en_wrapped,
        f_en,
        ink=ink,
        stroke_w=sw_en,
        stroke_fill=paper,
        bleed_blur=1.3,
        bleed_alpha=200,
        jitter=1
    )

    # 4) Composite & export
    out = Image.alpha_composite(img, canvas).convert("RGB")
    buf = io.BytesIO()
    if out_format.upper() == "PNG":
        out.save(buf, "PNG", optimize=True)
    else:
        out.save(buf, "JPEG", quality=jpeg_quality, subsampling=jpeg_subsampling,
                 optimize=True, progressive=progressive)
    return buf.getvalue()
