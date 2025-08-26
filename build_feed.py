#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
build_feed.py
Generates podcast.xml (RSS 2.0 + iTunes tags) from Jekyll posts.

Requirements (installed in CI step):
  pip install pyyaml requests

Usage:
  python build_feed.py
"""

import os, re, sys, html, hashlib
from pathlib import Path
from datetime import datetime, timezone
from email.utils import format_datetime
import yaml

ROOT = Path(__file__).resolve().parent
POSTS_DIR = ROOT / "_posts"
EPISODES_DIR = ROOT / "episodes"
OUT_PATH = ROOT / "podcast.xml"

# ------------------------------- helpers ---------------------------------- #

def read_yaml_config():
    cfg_path = ROOT / "_config.yml"
    cfg = {}
    if cfg_path.exists():
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    # Required for URL building
    site_url = (cfg.get("url") or "").rstrip("/")
    baseurl = (cfg.get("baseurl") or "")
    baseurl = "" if baseurl in (None, "", "/") else baseurl.rstrip("/")
    return cfg, site_url, baseurl

def absolute(site_url: str, baseurl: str, path_or_url: str) -> str:
    """Make an absolute URL from a site-local path; pass through if already absolute."""
    if not path_or_url:
        return ""
    if "://" in path_or_url:
        return path_or_url
    p = path_or_url if path_or_url.startswith("/") else "/" + path_or_url
    return f"{site_url}{baseurl}{p}"

def parse_front_matter(md_text: str):
    """Return (front_matter_dict, body) from a Jekyll post file."""
    if not md_text.startswith("---"):
        return {}, md_text
    # find closing ---
    end = md_text.find("\n---", 3)
    if end == -1:
        return {}, md_text
    fm_text = md_text[4:end]
    body = md_text[end+4:]
    if body.startswith("\n"):
        body = body[1:]
    try:
        fm = yaml.safe_load(fm_text) or {}
    except Exception:
        fm = {}
    return fm, body

def parse_post_filename(fn: str):
    """
    2025-08-21-yi-jian-zhong-qing.md -> (date_str, slug)
    """
    m = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)\.md$", fn)
    if not m:
        return None, None
    return m.group(1), m.group(2)

def parse_date(value, fallback_date_str: str):
    """
    Turn front-matter date (string or datetime) + filename date into a datetime.
    Output tz-aware UTC datetime (best effort).
    """
    if isinstance(value, datetime):
        dt = value
    else:
        dt = None
        if isinstance(value, str):
            # Try a few formats
            for fmt in (
                "%Y-%m-%d %H:%M:%S %z",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            ):
                try:
                    dt = datetime.strptime(value, fmt)
                    break
                except Exception:
                    pass
            if dt is None:
                # Try ISO
                try:
                    dt = datetime.fromisoformat(value)
                except Exception:
                    dt = None
    if dt is None:
        # build from filename date at 10:00:00 UTC by default
        try:
            d = datetime.strptime(fallback_date_str, "%Y-%m-%d")
            dt = datetime(d.year, d.month, d.day, 10, 0, 0)
        except Exception:
            dt = datetime.utcnow()
    # make tz-aware UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt

def permalink_for(date_str: str, slug: str) -> str:
    """Default Jekyll-style permalink for posts."""
    y, m, d = date_str.split("-")
    return f"/{y}/{m}/{d}/{slug}.html"

def text_or_empty(x):
    return "" if x is None else str(x)

# ------------------------------ channel meta -------------------------------- #

cfg, SITE_URL, BASEURL = read_yaml_config()

CHANNEL_TITLE = text_or_empty(cfg.get("title") or "Chengyu Bites")
CHANNEL_DESC  = text_or_empty(cfg.get("description") or "Short, conversational episodes exploring Chinese 成语.")
CHANNEL_LANG  = text_or_empty(cfg.get("language") or "en")
CHANNEL_AUTHOR= text_or_empty(cfg.get("author") or "Chengyu Bites")
CHANNEL_OWNER = text_or_empty(cfg.get("owner_name") or "Tilman")
CHANNEL_EMAIL = text_or_empty(cfg.get("owner_email") or "tkohlenberg@gmail.com")
CHANNEL_IMAGE = text_or_empty(cfg.get("cover_image") or "")  # optional site-wide image

SELF_URL = f"{SITE_URL}{BASEURL}/podcast.xml"

# ------------------------------ gather items -------------------------------- #

items = []

for post_path in sorted(POSTS_DIR.glob("*.md")):
    fn = post_path.name
    date_str, slug = parse_post_filename(fn)
    if not date_str:
        continue

    fm, _ = parse_front_matter(post_path.read_text(encoding="utf-8"))

    title = text_or_empty(fm.get("title") or slug)
    description = text_or_empty(fm.get("description") or "")
    cover_image = text_or_empty(fm.get("cover_image") or "")
    audio_url   = text_or_empty(fm.get("audio_url") or "")
    audio_bytes = fm.get("audio_bytes")

    # If audio_bytes missing, try local file
    if (audio_bytes is None) and audio_url:
        folder = f"{date_str}-{slug}"
        local_audio = EPISODES_DIR / folder / "audio.mp3"
        if local_audio.exists():
            try:
                audio_bytes = local_audio.stat().st_size
            except Exception:
                audio_bytes = None

    pub_dt = parse_date(fm.get("date"), date_str)
    pub_rfc2822 = format_datetime(pub_dt)  # RFC 2822 string

    # Build URLs
    link_rel = permalink_for(date_str, slug)                # site-local
    link_abs = absolute(SITE_URL, BASEURL, link_rel)
    audio_abs = absolute(SITE_URL, BASEURL, audio_url) if audio_url else ""
    image_abs = absolute(SITE_URL, BASEURL, cover_image) if cover_image else ""

    if not audio_abs:
        # Skip items without an audio enclosure
        print(f"[skip] {fn}: missing audio_url")
        continue

    # GUID: stable by permalink (not per audio file)
    guid = link_abs

    items.append({
        "title": title,
        "description": description,
        "link": link_abs,
        "guid": guid,
        "pubDate": pub_rfc2822,
        "enclosure_url": audio_abs,
        "enclosure_length": str(audio_bytes or 0),
        "enclosure_type": "audio/mpeg",
        "image": image_abs,
    })

# newest first
items.sort(key=lambda x: x["pubDate"], reverse=True)

# ------------------------------ build XML ----------------------------------- #

def x(value: str) -> str:
    """XML-escape text nodes."""
    return html.escape(value or "", quote=True)

now_rfc2822 = format_datetime(datetime.now(timezone.utc))

parts = []
parts.append('<?xml version="1.0" encoding="UTF-8"?>')
parts.append('<rss version="2.0"'
             ' xmlns:atom="http://www.w3.org/2005/Atom"'
             ' xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"'
             ' xmlns:content="http://purl.org/rss/1.0/modules/content/">')
parts.append("<channel>")

# Channel meta
parts.append(f"<title>{x(CHANNEL_TITLE)}</title>")
parts.append(f"<link>{x(f'{SITE_URL}{BASEURL}/')}</link>")
parts.append(f'<atom:link href="{x(SELF_URL)}" rel="self" type="application/rss+xml" />')
parts.append(f"<language>{x(CHANNEL_LANG)}</language>")
parts.append(f"<description>{x(CHANNEL_DESC)}</description>")
parts.append(f"<lastBuildDate>{x(now_rfc2822)}</lastBuildDate>")

# iTunes channel tags
parts.append(f"<itunes:author>{x(CHANNEL_AUTHOR)}</itunes:author>")
parts.append(f"<itunes:summary>{x(CHANNEL_DESC)}</itunes:summary>")
parts.append("<itunes:explicit>false</itunes:explicit>")
parts.append("<itunes:category text=\"Education\"/>")
parts.append("<itunes:category text=\"Language Learning\"/>")
parts.append("<itunes:owner>")
parts.append(f"  <itunes:name>{x(CHANNEL_OWNER)}</itunes:name>")
parts.append(f"  <itunes:email>{x(CHANNEL_EMAIL)}</itunes:email>")
parts.append("</itunes:owner>")

# Channel image: prefer config cover_image, else first item’s image if present
channel_image_abs = ""
if CHANNEL_IMAGE:
    channel_image_abs = absolute(SITE_URL, BASEURL, CHANNEL_IMAGE)
elif items and items[0].get("image"):
    channel_image_abs = items[0]["image"]

if channel_image_abs:
    parts.append("<image>")
    parts.append(f"  <url>{x(channel_image_abs)}</url>")
    parts.append(f"  <title>{x(CHANNEL_TITLE)}</title>")
    parts.append(f"  <link>{x(f'{SITE_URL}{BASEURL}/')}</link>")
    parts.append("</image>")
    parts.append(f'<itunes:image href="{x(channel_image_abs)}"/>')

# Items
for it in items:
    parts.append("<item>")
    parts.append(f"  <title>{x(it['title'])}</title>")
    parts.append(f"  <link>{x(it['link'])}</link>")
    parts.append(f'  <guid isPermaLink="false">{x(it["guid"])}</guid>')
    parts.append(f"  <pubDate>{x(it['pubDate'])}</pubDate>")
    # Simple description (plain text). If you want HTML, wrap in CDATA.
    if it["description"]:
        parts.append(f"  <description>{x(it['description'])}</description>")
        parts.append(f"  <itunes:summary>{x(it['description'])}</itunes:summary>")
    if it.get("image"):
        parts.append(f'  <itunes:image href="{x(it["image"])}"/>')
    parts.append(f'  <enclosure url="{x(it["enclosure_url"])}" length="{x(it["enclosure_length"])}" type="{x(it["enclosure_type"])}" />')
    parts.append("</item>")

parts.append("</channel>")
parts.append("</rss>")

xml = "\n".join(parts) + "\n"
OUT_PATH.write_text(xml, encoding="utf-8")

print(f"Wrote podcast.xml with {len(items)} items to {OUT_PATH}")
if not items:
    print("WARNING: No items were written. Check that your posts have audio_url in front matter.")
else:
    # print a small summary
    print("\nTop 3 items:")
    for it in items[:3]:
        print(f" - {it['title']} -> {it['enclosure_url']}")
