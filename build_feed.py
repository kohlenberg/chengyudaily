#!/usr/bin/env python3
# build_feed.py — generate podcast.xml with formatted show notes from post Markdown
# Requirements: PyYAML, markdown  (pip install pyyaml markdown)

import os, re, sys, html
from pathlib import Path
from datetime import datetime, timezone
from email.utils import format_datetime
import yaml
import markdown

ROOT = Path(__file__).resolve().parent
POSTS_DIR = ROOT / "_posts"
EPISODES_DIR = ROOT / "episodes"
OUT_FILE = ROOT / "podcast.xml"

# ---------- config / helpers ----------

def load_config():
    cfg_path = ROOT / "_config.yml"
    data = {}
    if cfg_path.exists():
        try:
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    return {
        "title":      data.get("title", "Chengyu Bites"),
        "description":data.get("description", "Short, conversational episodes exploring Chinese 成语."),
        "author":     data.get("author", "Chengyu Bites"),
        "email":      data.get("email", "podcast@example.com"),
        "site_url":   data.get("url", "https://kohlenberg.github.io/chengyudaily").rstrip("/"),
        "baseurl":    (data.get("baseurl", "/chengyudaily") or "").rstrip("/"),
        "language":   data.get("language", "en"),
        "category":   data.get("category", "Education"),
        "explicit":   str(data.get("explicit", "false")).lower(),
        "image":      data.get("cover_image") or data.get("image") or "/assets/cover.jpg",
        "owner_name": data.get("owner_name", data.get("author", "Chengyu Bites")),
        "owner_email":data.get("owner_email", data.get("email", "podcast@example.com")),
        "copyright":  data.get("copyright", f"© {datetime.now().year} {data.get('author','Chengyu Bites')}"),
        "itunes_type":data.get("itunes_type", "episodic"),
        "future":     bool(data.get("future", False)),
        "timezone":   data.get("timezone", "UTC"),
    }

def abs_url(site_url: str, baseurl: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return f"{site_url}{baseurl}{path}"

def parse_front_matter(md_path: Path):
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
    if not audio_url:
        return None
    m = re.search(r"/episodes/.*\.mp3$", audio_url)
    if not m:
        return None
    rel = m.group(0).lstrip("/")
    fs = ROOT / rel
    if fs.exists():
        try:
            return fs.stat().st_size
        except Exception:
            return None
    return None

def rfc2822(dt_str: str) -> str:
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return format_datetime(dt)
    except Exception:
        return format_datetime(datetime.utcnow().replace(tzinfo=timezone.utc))

# ---------- show-notes rendering ----------

# Keep show notes within ~4000 chars to be safe across podcast apps:
MAX_DESC_CHARS = 3800

IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
SCRIPT_STYLE = re.compile(r"</?(?:script|style)\b[^>]*>", re.IGNORECASE)

def markdown_to_html(md_text: str) -> str:
    # Render conservative HTML; no codehilite, no raw HTML passthrough
    return markdown.markdown(
        md_text or "",
        extensions=["extra", "sane_lists", "nl2br"],
        output_format="xhtml"
    )

def clean_notes_html(html_in: str) -> str:
    # strip <img>, <script>, <style>
    s = IMG_TAG.sub("", html_in)
    s = SCRIPT_STYLE.sub("", s)
    return s.strip()

def make_notes_html(body_md: str, episode_url: str) -> tuple[str, str]:
    """
    Return (desc_html_trimmed, full_notes_html).
    - full_notes_html: full rendered notes from the post body, plus a footer link.
    - desc_html_trimmed: trimmed version for <description>.
    """
    full_html = clean_notes_html(markdown_to_html(body_md))
    # add a small footer link to the web page
    full_html += f'\n<p><a href="{episode_url}">View this episode on the web</a></p>'

    # Trim for show notes (<description>)
    # We trim by plain-text length but keep the HTML; CDATA will carry it fine.
    text_len = 0
    out = []
    for ch in full_html:
        # approximate count of visible text
        if ch != "<":  # naive, but ok for our use (CDATA tolerates broken tags anyway)
            text_len += 1
        out.append(ch)
        if text_len >= MAX_DESC_CHARS:
            out.append("…")
            break
    desc_html = "".join(out)
    return desc_html, full_html

# ---------- channel image ----------

def pick_channel_image(cfg: dict) -> str:
    img = cfg["image"]
    if img:
        return abs_url(cfg["site_url"], cfg["baseurl"], img)
    for md in sorted(POSTS_DIR.glob("*.md")):
        fm, _ = parse_front_matter(md)
        cov = fm.get("cover_image")
        if cov:
            return abs_url(cfg["site_url"], cfg["baseurl"], cov)
    return abs_url(cfg["site_url"], cfg["baseurl"], "/assets/cover.jpg")

# ---------- main build ----------

def main():
    cfg = load_config()

    head = []
    head.append('<?xml version="1.0" encoding="UTF-8"?>')
    head.append('<rss version="2.0"')
    head.append('     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"')
    head.append('     xmlns:content="http://purl.org/rss/1.0/modules/content/"')
    head.append('     xmlns:atom="http://www.w3.org/2005/Atom"')
    head.append('     xmlns:podcast="https://podcastindex.org/namespace/1.0">')
    head.append('<channel>')

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
        fm, body_md = parse_front_matter(md)

        # date/future filtering
        date_str = str(fm.get("date", "")).strip()
        if date_str:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if (not cfg["future"]) and dt > datetime.now(timezone.utc):
                    continue
            except Exception:
                pass

        title = fm.get("title", md.stem)
        desc_short = fm.get("description", "")  # used as a short intro at the top of notes
        cover = fm.get("cover_image")
        audio_url = fm.get("audio_url", "")

        date = md.name[:10]
        slug = md.stem[11:]
        folder = f"{date}-{slug}"

        # URLs
        page_url = abs_url(cfg["site_url"], cfg["baseurl"], f"/{date.replace('-','/')}/{slug}.html")
        cover_abs = abs_url(cfg["site_url"], cfg["baseurl"], cover) if cover else channel_image
        audio_abs = abs_url(cfg["site_url"], cfg["baseurl"], audio_url) if audio_url else ""

        # enclosure length
        enclosure_len = None
        if "audio_bytes" in fm:
            try:
                enclosure_len = int(fm["audio_bytes"])
            except Exception:
                enclosure_len = None
        if enclosure_len is None and audio_url:
            enclosure_len = file_size_bytes_from_audio_url(audio_url, folder)

        # formatted notes from Markdown body
        # prepend the short description (bold) if present
        body_with_intro = (f"**{desc_short}**\n\n" if desc_short else "") + (body_md or "")
        desc_notes_html, full_notes_html = make_notes_html(body_with_intro, page_url)

        # (optional) transcript link via Podcasting 2.0
        tx = read_transcript(folder)

        # build <item>
        item = []
        item.append("  <item>")
        item.append(f"    <title>{html.escape(title)}</title>")
        item.append(f"    <link>{page_url}</link>")
        item.append(f"    <guid isPermaLink=\"true\">{page_url}</guid>")
        pubdate = rfc2822(date_str or "")
        item.append(f"    <pubDate>{pubdate}</pubDate>")

        # show notes
        item.append(f"    <description><![CDATA[{desc_notes_html}]]></description>")
        item.append(f"    <content:encoded><![CDATA[{full_notes_html}]]></content:encoded>")

        # image per episode
        if cover_abs:
            item.append(f'    <itunes:image href="{cover_abs}"/>')

        # audio enclosure
        if audio_abs:
            length_attr = f' length="{enclosure_len}"' if (enclosure_len is not None) else ""
            item.append(f'    <enclosure url="{audio_abs}" type="audio/mpeg"{length_attr} />')

        # keep a short itunes:summary from the description only
        if desc_short:
            item.append(f"    <itunes:summary>{html.escape(desc_short)}</itunes:summary>")

        # podcast:transcript tag
        if tx:
            tx_abs = abs_url(cfg["site_url"], cfg["baseurl"], f"/episodes/{folder}/transcript.txt")
            item.append(f'    <podcast:transcript url="{tx_abs}" type="text/plain" />')

        item.append("  </item>")
        items_xml.append("\n".join(item))

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
