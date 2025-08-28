# chengyu/cover_flow.py
# Utilities to generate a cover with hybrid method + "dark-top" safety.

import io
from PIL import Image
from chengyu.config import settings
from chengyu.cover_hybrid import generate_cover_hybrid

def top_too_dark(img_bytes: bytes, frac: float = 0.18, lum_thresh: int = 35, max_ratio: float = 0.16) -> bool:
    """Detect a very dark top band."""
    im = Image.open(io.BytesIO(img_bytes)).convert("L")
    h = max(1, int(im.height * frac))
    roi = im.crop((0, 0, im.width, h))
    hist = roi.histogram()
    dark = sum(hist[:max(0, lum_thresh)])
    total = roi.width * roi.height
    return (dark / max(1, total)) > max_ratio

def make_cover_bytes(
    data: dict,
    *,
    attempts: int = 4,
    out_format: str = "JPEG",   # "JPEG" (smaller) or "PNG"
    pinyin_y: float = 0.50,
    english_y: float = 0.78
):
    """
    Generate cover bytes for an episode dict using hybrid method.
    Retries a few times if the top is too dark.
    Returns (bytes, 'jpg'|'png').
    """
    for i in range(1, attempts + 1):
        cover = generate_cover_hybrid(
            chengyu=data["chengyu"],
            pinyin=data["pinyin"],
            english=data["gloss"],
            story=data["script"],
            model=getattr(settings, "IMAGE_MODEL", "gpt-image-1"),
            size=getattr(settings, "IMAGE_SIZE", "1024x1024"),
            quality="medium",
            out_size=1500,
            out_format=out_format,
            pinyin_y=pinyin_y,
            english_y=english_y,
        )
        if not top_too_dark(cover):
            if i > 1:
                print(f"Accepted attempt {i} (top ok).")
            return cover, ("jpg" if out_format.upper() == "JPEG" else "png")
        print(f"Attempt {i}: top too dark → retrying…")

    print("Warning: top remained dark after retries; using last image.")
    return cover, ("jpg" if out_format.upper() == "JPEG" else "png")
