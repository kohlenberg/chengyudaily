import io, textwrap
from PIL import Image, ImageDraw, ImageFont

def _ensure_font(size: int):
    for cand in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]:
        try:
            return ImageFont.truetype(cand, size)
        except Exception:
            pass
    return ImageFont.load_default()

def draw_cover_png(show_name: str, chengyu: str, pinyin: str, gloss: str) -> bytes:
    W = H = 3000
    bg = "#0e1116"
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)

    font_show = _ensure_font(120)
    font_cn   = _ensure_font(440)
    font_py   = _ensure_font(150)
    font_gl   = _ensure_font(90)

    d.text((150, 180), show_name, font=font_show, fill=(180,200,255))

    bbox_cn = d.textbbox((0,0), chengyu, font=font_cn)
    w_cn = bbox_cn[2]-bbox_cn[0]; h_cn = bbox_cn[3]-bbox_cn[1]
    x_cn = (W - w_cn)//2; y_cn = (H - h_cn)//2 - 140
    d.text((x_cn, y_cn), chengyu, font=font_cn, fill=(255,255,255))

    bbox_py = d.textbbox((0,0), pinyin, font=font_py)
    w_py = bbox_py[2]-bbox_py[0]
    x_py = (W - w_py)//2; y_py = y_cn + h_cn + 60
    d.text((x_py, y_py), pinyin, font=font_py, fill=(200,220,255))

    gloss_wrapped = textwrap.fill(gloss, width=30)
    d.multiline_text((150, H-520), gloss_wrapped, font=font_gl, fill=(160,180,220), spacing=12)

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
