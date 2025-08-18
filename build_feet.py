import re, os, email.utils, hashlib
from pathlib import Path
import yaml, requests
from datetime import datetime

SITE = "https://kohlenberg.github.io/chengyudaily/"
FEED = Path("podcast.xml")

def parse_front_matter(md_path: Path):
    text = md_path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, flags=re.S)
    if not m:
        return {}, text
    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)
    return fm, body

def rfc2822(date_str: str) -> str:
    # Expected like "2025-08-18 10:00:00 +0000"
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")
        return email.utils.format_datetime(dt)
    except Exception:
        # fallback to now
        return email.utils.formatdate(usegmt=True)

def full_url(path_or_url: str) -> str:
    if not path_or_url:
        return ""
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url
    return SITE.rstrip("/") + "/" + path_or_url.lstrip("/")

def ensure_length(audio_url: str, audio_bytes_meta):
    if audio_bytes_meta:
        return str(audio_bytes_meta)
    # try HEAD to fetch Content-Length
    try:
        r = requests.head(audio_url, timeout=20, allow_redirects=True)
        ln = r.headers.get("Content-Length")
        if ln: return ln
    except Exception:
        pass
    return None  # required by podcast directories; skip item if missing

def build_item(fm: dict):
    title = fm.get("title","").strip()
    desc  = (fm.get("description","") or "").strip()
    link  = full_url(fm.get("permalink") or fm.get("url") or "/")
    audio = fm.get("audio_url","").strip()
    cover = full_url(fm.get("cover_image",""))
    pub   = rfc2822(str(fm.get("date")))
    length = ensure_length(audio, fm.get("audio_bytes"))

    if not (title and audio and length):
        # Skip items without mandatory fields
        return None

    guid = hashlib.sha1((audio or title).encode("utf-8")).hexdigest()

    return f"""
    <item>
      <title>{title}</title>
      <description><![CDATA[{desc}]]></description>
      <link>{link}</link>
      <guid isPermaLink="false">{guid}</guid>
      <pubDate>{pub}</pubDate>
      <enclosure url="{audio}" length="{length}" type="audio/mpeg"/>
      <itunes:image href="{cover}"/>
      <itunes:explicit>false</itunes:explicit>
    </item>""".strip()

def main():
    posts = sorted(Path("_posts").glob("*.md"), reverse=True)
    items = []
    for p in posts:
        fm, _ = parse_front_matter(p)
        # Best-effort permalink if missing (Jekyll will generate its own; this is just a link)
        if "permalink" not in fm and "url" not in fm:
            fm["permalink"] = f"{p.stem}.html"
        item = build_item(fm)
        if item:
            items.append(item)

    channel = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Chengyu Bites</title>
    <link>{SITE}</link>
    <language>en</language>
    <description>Short, conversational episodes exploring Chinese chengyu (成语) with origins, examples, and TTS audio.</description>
    <itunes:author>Kohlenberg</itunes:author>
    <itunes:owner>
      <itunes:name>Kohlenberg</itunes:name>
      <itunes:email>your-email@example.com</itunes:email>
    </itunes:owner>
    <itunes:explicit>false</itunes:explicit>
    <itunes:image href="{SITE}cover-3000.png"/>
    <itunes:category text="Education"/>
{chr(10).join(items)}
  </channel>
</rss>
"""
    FEED.write_text(channel.strip() + "\n", encoding="utf-8")
    print("Wrote", FEED.resolve())

if __name__ == "__main__":
    main()
