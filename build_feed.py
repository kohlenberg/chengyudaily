#!/usr/bin/env python3
# build_feed.py — generate podcast.xml with transcript excerpts + full transcript blocks
# Requirements: PyYAML
# Usage: python build_feed.py

import os, re, sys, html, json
from pathlib import Path
from datetime import datetime, timezone
from email.utils import format_datetime
import yaml

ROOT = Path(__file__).resolve().parent
POSTS_DIR = ROOT / "_posts"
EPISODES_DIR = ROOT / "episodes"
OUT_FILE = ROOT / "podcast.xml"

# -------- helpers --------

def load_config():
    cfg_path = ROOT / "_config.yml"
    data = {}
    if cfg_path.exists():
        try:
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    # sensible defaults + _config.yml overrides
    return {
        "title": data.get("title", "Chengyu Bites"),
        "description": data.get("description", "Short, conversational episodes exploring Chinese 成语."),
        "author": data.get("author", "Chengyu Bites"),
        "email": data.get("email", "podcast@example.com"),
        "site_url": data.get("url", "https://kohlenberg.github.io/chengyudaily").rstrip("/"),
        "baseurl": (data.get("baseurl", "/chengyudaily") or "").rstrip("/"),
        "language": data.get("language", "en"),
        "category": data.get("category", "Education"),
        "explicit": str(data.get("explicit", "false")).lower(),
        "image": data.get("cover_image") or data.get("image") or "/assets/cover.jpg",
        "owner_name": data.get("owner_name", data.get("author", "Chengyu Bites")),
        "owner_email": data.get("owner_email", data.get("email", "podcast@example.com")),
        "copyright": data.get("copyright", f"© {datetime.now().year} {data.get('author','Chengyu Bites')}"),
        "itunes_type": data.get("itunes_type", "episodic"),
        "future": bool(data.get("future", False)),
        "timezone": data.get("timezone", "UTC"),
    }

def abs_url(site_url: str, baseurl: str, path: str) -> str:
    """Make an absolute URL; path may already be absolute or start with /."""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return f"{site_url}{baseurl}{path}"

def parse_front_matter(md_path: Path):
    """Return (front_matter_dict, body_md_str)."""
    text = md_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_text = text[4:end]
    body = text[end+4:]
    if body.startswith("\n"):
        body = body[1:]
    try:
        fm = yaml.safe_load(fm_text) or {}
    except Exception:
        fm = {}
    return fm, body

def md_file_to_folder(md_path: Path) -> str:
    date = md_path.name[:10]
    slug = md_path.stem[11:]
    return f"{date}-{slug}"

def read_transcript(folder: str) -> str | None:
    p = EPISODES_DIR / folder / "transcript.txt"
    if p.exists():
        try:
            return p.read_text(encoding="utf-8").strip()
        except Exception:
            return None
    return None

def file_size_bytes_from_audio_url(audio_url: str, folder: str) -> int | None:
    """If audio_url points inside this repo (/episodes/<folder>/audio.mp3), read size."""
    if not audio_url:
        return None
    # normalize: /episodes/<folder>/audio.mp3
    if "/episodes/" in audio_url and audio_url.endswith(".mp3"):
        # pull relative after baseurl if present
        rel = audio_url
        # strip domain if absolute
        m = re.search(r"/episodes/.*\.mp3$", audio_url)
        if m:
            rel = m.group(0).lstrip("/")
        fs = ROOT / rel
        if fs.exists():
            try:
                return fs.stat().st_size
            except Exception:
                return None
    return None

def rfc2822(dt_str: str) -> str:
    # dt_str like "YYYY-MM-DD HH:MM:SS" (UTC). If missing, use file mtime.
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return format_datetime(dt)
    except Exception:
        return format_datetime(datetime.utcnow().replace(tzinfo=timezone.utc))

MAX_DESC_CHARS = 3800

def build_desc_and_full(desc_text: str, full_tx: str, episode_url: str) -> tuple[str, str]:
    esc_desc = html.escape(desc_text or "")
    esc_full = html.escape(full_tx or "")
    excerpt = esc_full[:MAX_DESC_CHARS]
    if len(esc_full) > MAX_DESC_CHARS:
        excerpt += "…"
    desc_html = (
        f"{esc_desc}\n\n"
        f"<h3>Transcript</h3>\n"
        f"{excerpt}\n\n"
        f"<a href=\"{episode_url}\">Read the full transcript</a>"
    )
    full_html = (
        f"<h3>Transcript</h3>\n"
        f"{esc_full}\n\n"
        f"<a href=\"{episode_url}\">View on the web</a>"
    )
    return desc_html, full_html

def pick_channel_image(cfg: dict) -> str:
    # Prefer config image; else first episode cover
    img = cfg["image"]
    if img:
        return abs_url(cfg["site_url"], cfg["baseurl"], img)
    # fallback scan
    for md in sorted(POSTS_DIR.glob("*.md")):
        fm, _ = parse_front_matter(md)
        cov = fm.get("cover_image")
        if cov:
            return abs_url(cfg["site_url"], cfg["baseurl"], cov)
    return abs_url(cfg["site_url"], cfg["baseurl"], "/assets/cover.jpg")

# -------- main build --------

def main():
    cfg = load_config()

    # rss header
    head = []
    head.append('<?xml version="1.0" encoding="UTF-8"?>')
    head.append('<rss version="2.0"')
    head.append('     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"')
    head.append('     xmlns:content="http://purl.org/rss/1.0/modules/content/"')
    head.append('     xmlns:atom="http://www.w3.org/2005/Atom"')
    head.append('     xmlns:podcast="https://podcastindex.org/namespace/1.0">')
    head.append('<channel>')

    # channel metadata
    channel_image = pick_channel_image(cfg)
    head.append(f'  <title>{html.escape(cfg["title"])}</title>')
    head.append(f'  <link>{cfg["site_url"]}{cfg["baseurl"]}</link>')
    head.append(f'  <language>{cfg["language"]}</language>')
    head.append(f'  <itunes:author>{html.escape(cfg["author"])}</itunes:author>')
    head.append(f'  <itunes:summary>{html.escape(cfg["description"])}</itunes:summary>')
    head.append(f'  <description>{html.escape(cfg["description"])}</description>')
    head.append(f'  <itunes:explicit>{cfg["explicit"]}</itunes:explicit>')
    head.append(f'  <itunes:owner><itunes:name>{html.escape(cfg["owner_name"])}</itunes:name><itunes:email>{html.escape(cfg["owner_email"])}</itunes:email></itunes:owner>')
    head.append(f'  <itunes:image href="{channel_image}"/>')
    head.append(f'  <itunes:category text="{html.escape(cfg["category"])}"/>')
    head.append(f'  <itunes:type>{html.escape(cfg["itunes_type"])}</itunes:type>')
    head.append(f'  <atom:link href="{cfg["site_url"]}{cfg["baseurl"]}/podcast.xml" rel="self" type="application/rss+xml" />')
    head.append(f'  <copyright>{html.escape(cfg["copyright"])}</copyright>')

    items_xml = []

    posts = sorted(POSTS_DIR.glob("*.md"))
    if not posts:
        print("No posts found in _posts/")
    for md in posts:
        fm, body = parse_front_matter(md)

        # date & future filter
        date_str = str(fm.get("date", "")).strip()
        if date_str:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if (not cfg["future"]) and dt > datetime.now(timezone.utc):
                    # skip future post unless cfg.future = true
                    continue
            except Exception:
                pass

        # basic fields
        title = fm.get("title", md.stem)
        desc  = fm.get("description", "")
        cover = fm.get("cover_image")  # relative
        audio_url = fm.get("audio_url", "")

        date = md.name[:10]
        slug = md.stem[11:]
        folder = f"{date}-{slug}"

        # URLs
        page_url = abs_url(cfg["site_url"], cfg["baseurl"], f"/{date.replace('-','/')}/{slug}.html")
        cover_abs = abs_url(cfg["site_url"], cfg["baseurl"], cover) if cover else channel_image
        audio_abs = abs_url(cfg["site_url"], cfg["baseurl"], audio_url) if audio_url else ""

        # enclosure length (prefer fm.audio_bytes; else file size if local; else blank)
        enclosure_len = None
        if "audio_bytes" in fm:
            try:
                enclosure_len = int(fm["audio_bytes"])
            except Exception:
                enclosure_len = None
        if enclosure_len is None and audio_url:
            enclosure_len = file_size_bytes_from_audio_url(audio_url, folder)

        # transcript
        tx = read_transcript(folder)
        if tx:
            desc_html, full_html = build_desc_and_full(desc, tx, page_url)
        else:
            # plain description only
            desc_html, full_html = html.escape(desc or ""), None

        # build <item>
        item = []
        item.append("  <item>")
        item.append(f"    <title>{html.escape(title)}</title>")
        item.append(f"    <link>{page_url}</link>")
        item.append(f"    <guid isPermaLink=\"true\">{page_url}</guid>")
        pubdate = rfc2822(date_str or "")
        item.append(f"    <pubDate>{pubdate}</pubDate>")

        # description + content:encoded
        item.append(f"    <description><![CDATA[{desc_html}]]></description>")
        if full_html:
            item.append(f"    <content:encoded><![CDATA[{full_html}]]></content:encoded>")

        # itunes:image per-episode
        if cover_abs:
            item.append(f'    <itunes:image href="{cover_abs}"/>')

        # enclosure
        if audio_abs:
            length_attr = f' length="{enclosure_len}"' if (enclosure_len is not None) else ""
            item.append(f'    <enclosure url="{audio_abs}" type="audio/mpeg"{length_attr} />')
        # itunes:summary (short)
        if desc:
            item.append(f"    <itunes:summary>{html.escape(desc)}</itunes:summary>")

        # podcast:transcript (plain text)
        if tx:
            tx_abs = abs_url(cfg["site_url"], cfg["baseurl"], f"/episodes/{folder}/transcript.txt")
            item.append(f'    <podcast:transcript url="{tx_abs}" type="text/plain" />')

        item.append("  </item>")
        items_xml.append("\n".join(item))

    # close channel+rss
    xml = []
    xml.extend(head)
    xml.extend(items_xml)
    xml.append("</channel>")
    xml.append("</rss>\n")

    OUT_FILE.write_text("\n".join(xml), encoding="utf-8")
    print(f"Wrote {OUT_FILE.relative_to(ROOT)} with {len(items_xml)} item(s).")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Failed to build feed:", e)
        sys.exit(1)
