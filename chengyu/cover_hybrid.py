# Hybrid cover generator (no hard bands):
# - Model paints: background + EXACT Chinese characters (brush calligraphy) + red seal
# - Pillow overlays: pinyin + English with brushy look AND a local, feathered paper backdrop
# - 1500×1500 JPEG by default; PNG supported

import io, re, base64
from typing import Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from openai import OpenAI

SUPPORTED_SIZES = {"1024x1024", "1024x1536", "1536x1024", "auto"}

def _norm_size(size: str) -> str:
    s = (size or "1024x1024").lower()
    return s if s in SUPPORTED_SIZES else "1024x1024"

def _pick_font(paths, size: int) -> ImageFont.FreeTypeFont:
    for p in paths:
        try: return ImageFont.truetype(p, size)
        except Exception: pass
    return ImageFont.load_default()

def _font_pinyin(size: int) -> ImageFont.FreeTypeFont:
    return _pick_font([
        "assets/fonts/Kalam-Regular.ttf",
        "assets/fonts/PatrickHand-Regular.ttf",
        "assets/fonts/GentiumPlus-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/Library/Fonts/Times New Roman.ttf",
    ], size)

def _font_english(size: int) -> ImageFont.FreeTypeFont:
    return _pick_font([
        "assets/fonts/Kalam-Regular.ttf",
        "assets/fonts/PatrickHand-Regular.ttf",
        "assets/fonts/EBGaramond-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/Library/Fonts/Times New Roman.ttf",
    ], size)

def _sanitize_english(s: str) -> str:
    if not s: return ""
    trans = {0x00B4:ord("'"),0x2018:ord("'"),0x2019:ord("'"),
             0x201C:ord('"'),0x201D:ord('"'),0x02BC:ord("'"),0x02C8:ord("'")}
    return re.sub(r"\s+"," ", s.translate(trans)).strip()

def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, stroke_w: int = 0) -> Tuple[int,int]:
    lines = text.split("\n")
    w=h=0
    for i,line in enumerate(lines):
        bbox = draw.textbbox((0,0), line, font=font, stroke_width=stroke_w)
        lw, lh = bbox[2]-bbox[0], bbox[3]-bbox[1]
        w = max(w,lw); h += lh + (8 if i < len(lines)-1 else 0)
    return w,h

def _fit_single_line(draw, text, font_picker, max_width, start=176, min_size=96, stroke_ratio=0.06):
    size = start
    while size >= min_size:
        f = font_picker(size); sw = max(2, int(size*stroke_ratio))
        w,_ = _measure(draw, text, f, stroke_w=sw)
        if w <= max_width: return f, sw
        size -= 6
    f = font_picker(min_size); sw = max(2, int(min_size*stroke_ratio))
    return f, sw

def _wrap_to_width(draw, text, font_picker, max_width, max_lines=2, start=140, min_size=90, stroke_ratio=0.05):
    words = (text or "").split()
    size = start
    while size >= min_size:
        f = font_picker(size); sw = max(2, int(size*stroke_ratio))
        lines, line = [], ""
        for w in words:
            test = (line+" "+w).strip()
            tw,_ = _measure(draw, test, f, stroke_w=sw)
            if tw <= max_width or not line:
                line = test
            else:
                lines.append(line); line = w
                if len(lines) >= max_lines: lines=None; break
        if lines is not None:
            if line: lines.append(line)
            if all(_measure(draw, ln, f, stroke_w=sw)[0] <= max_width for ln in lines):
                return "\n".join(lines), f, sw
        size -= 6
    f = font_picker(min_size); sw = max(2, int(min_size*stroke_ratio))
    # best-effort wrap
    lines, line = [], ""
    for w in words:
        test=(line+" "+w).strip()
        tw,_ = _measure(ImageDraw.Draw(Image.new("RGB",(10,10))), test, f, stroke_w=sw)
        if tw <= max_width or not line: line = test
        else:
            lines.append(line); line = w
            if len(lines) >= max_lines: break
    if line and len(lines)<max_lines: lines.append(line)
    return "\n".join(lines[:max_lines]), f, sw

# ---- brushy text & local paper backdrop (no full-width band)

def _draw_brushy_soft_text(canvas, xy, text, font,
                           ink=(44,38,32), stroke_w=8, stroke_fill=(246,242,235),
                           anchor="mm", bleed_blur=1.4, bleed_alpha=210, jitter=1):
    W,H = canvas.size; cx,cy = xy
    # under-ink bleed
    under = Image.new("RGBA",(W,H),(0,0,0,0))
    ImageDraw.Draw(under).text((cx,cy), text, font=font, fill=(0,0,0,bleed_alpha), anchor=anchor)
    under = under.filter(ImageFilter.GaussianBlur(bleed_blur))
    canvas.alpha_composite(under)
    # jitter mid-pass
    mid = Image.new("RGBA",(W,H),(0,0,0,0)); dm = ImageDraw.Draw(mid)
    for dx,dy in [(-jitter,0),(jitter,0)]:
        dm.text((cx+dx,cy+dy), text, font=font, fill=(20,18,16,120), anchor=anchor)
    canvas.alpha_composite(mid)
    # main
    d = ImageDraw.Draw(canvas)
    d.text((cx,cy), text, font=font, fill=ink, stroke_width=stroke_w, stroke_fill=stroke_fill, anchor=anchor)

def _paper_backdrop(canvas, xy, text, font, stroke_w, anchor="mm",
                    pad_x=40, pad_y=28, radius=28, tone=(246,242,235), blur=18, alpha=84):
    """Soft rounded rectangle behind the text only (no full-width edge)."""
    W,H = canvas.size; cx,cy = xy
    dtmp = ImageDraw.Draw(Image.new("RGBA",(1,1)))
    w,h = _measure(dtmp, text, font, stroke_w=stroke_w)
    # anchor center (mm)
    x0 = int(cx - w/2 - pad_x); y0 = int(cy - h/2 - pad_y)
    x1 = int(cx + w/2 + pad_x); y1 = int(cy + h/2 + pad_y)
    r  = max(8, radius)
    back = Image.new("RGBA",(W,H),(0,0,0,0))
    db = ImageDraw.Draw(back)
    try:
        db.rounded_rectangle([x0,y0,x1,y1], radius=r, fill=(*tone, alpha))
    except Exception:
        db.rectangle([x0,y0,x1,y1], fill=(*tone, alpha))
    back = back.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(back)

# ---- image background with characters

def _ai_bg_with_chars(chengyu: str, pinyin: str, english: str, story: str,
                      model: str, size: str, quality: str = "medium") -> Image.Image:
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
- Keep canvas edges light; avoid solid dark bands at the top.
- Avoid star-like gold speckles or granular spray at the top edge.
- Leave room below the characters for small Latin text additions later.
- No borders, frames, or watermarks.
"""
    res = client.images.generate(model=model, prompt=prompt, size=size, quality=quality)
    return Image.open(io.BytesIO(base64.b64decode(res.data[0].b64_json))).convert("RGBA")

# ---- main API

def generate_cover_hybrid(
    *,
    chengyu: str,
    pinyin: str,
    english: str,
    story: str = "",
    model: str = "gpt-image-1",
    size: str = "1024x1024",
    quality: str = "medium",
    out_size: int = 1500,
    out_format: str = "JPEG",
    jpeg_quality: int = 82,
    jpeg_subsampling: int = 2,
    progressive: bool = True,
    pinyin_y: float = 0.50,   # higher, just under the characters
    english_y: float = 0.78
) -> bytes:

    # background (with characters from the model)
    img = _ai_bg_with_chars(chengyu, pinyin, english, story, model=model, size=size, quality=quality)
    if img.size != (out_size, out_size):
        img = img.resize((out_size, out_size), Image.LANCZOS)
    W = H = out_size

    # overlay canvas
    overlay = Image.new("RGBA", (W,H), (0,0,0,0))
    d = ImageDraw.Draw(overlay)

    # fonts & palette
    f_py_picker = _font_pinyin
    f_en_picker = _font_english
    ink   = (44,38,32)
    paper = (246,242,235)
    cx    = W//2
    side_pad = int(W*0.10)
    max_w = W - 2*(side_pad + 20)

    # --- Pinyin: auto-fit; local soft paper backdrop + brushy text
    pinyin = (pinyin or "").strip()
    f_py, sw_py = _fit_single_line(d, pinyin, f_py_picker, max_width=max_w, start=176, min_size=96, stroke_ratio=0.06)
    py_xy = (cx, int(H * pinyin_y))
    _paper_backdrop(overlay, py_xy, pinyin, f_py, stroke_w=sw_py, pad_x=38, pad_y=24, radius=26, blur=20, alpha=82)
    _draw_brushy_soft_text(overlay, py_xy, pinyin, f_py, ink=ink, stroke_w=sw_py, stroke_fill=paper,
                           bleed_blur=1.4, bleed_alpha=210, jitter=1)

    # --- English: sanitize → wrap & auto-fit; local backdrop + brushy text
    en_text = _sanitize_english(english)
    en_wrapped, f_en, sw_en = _wrap_to_width(d, en_text, f_en_picker, max_width=max_w, max_lines=2,
                                             start=140, min_size=90, stroke_ratio=0.05)
    en_xy = (cx, int(H * english_y))
    _paper_backdrop(overlay, en_xy, en_wrapped, f_en, stroke_w=sw_en, pad_x=34, pad_y=22, radius=24, blur=18, alpha=78)
    _draw_brushy_soft_text(overlay, en_xy, en_wrapped, f_en, ink=ink, stroke_w=sw_en, stroke_fill=paper,
                           bleed_blur=1.3, bleed_alpha=200, jitter=1)

    # composite & export
    out = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    if out_format.upper() == "PNG":
        out.save(buf, "PNG", optimize=True)
    else:
        # If you suspect chroma banding, set subsampling=0 (larger file)
        out.save(buf, "JPEG", quality=jpeg_quality, subsampling=jpeg_subsampling,
                 optimize=True, progressive=progressive)
    return buf.getvalue()
