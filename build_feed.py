#!/usr/bin/env python3
# build_feed.py — generate podcast.xml with formatted show notes from post Markdown
# Requirements: PyYAML, Markdown  (pip install pyyaml markdown)

import os, re, sys, html
from pathlib import Path
from datetime import datetime, timezone, timedelta
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
        "site_url":   (data.get("url", "https://kohlenberg.github.io/chengyudaily") or "").rstrip("/"),
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
    """Return absolute URL for a given site/base/path combo."""
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
    """
    If audio_url points to /episodes/<folder>/audio.mp3 inside this repo,
    get the file size for enclosure length.
    """
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

def compute_pub_dt(md_path: Path, fm: dict) -> datetime:
    """
    Return a timezone-aware UTC datetime for this episode.
    Priority: front-matter 'date' -> filename date (noon UTC) -> file mtime.
    """
    ds = str(fm.get("date", "")).strip()
    if ds:
        try:
            return datetime.strptime(ds, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            pass
    # filename date
    try:
        y, m, d = map(int, md_path.name[:10].split("-"))
        return datetime(y, m, d, 12, 0, 0, tzinfo=timezone.utc)
    except Exception:
        pass
    # file mtime
    return datetime.fromtimestamp(md_path.stat().st_mtime, tz=timezone.utc)

def rfc2822_from_dt(dt: datetime) -> str:
    return format_datetime(dt)

# ---------- show-notes rendering ----------

# Keep show notes within ~4000 chars to be safe across podcast apps:
MAX_DESC_CHARS = 3800

IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
SCRIPT_STYLE = re.compile(r"</?(?:script|style)\b[^>]*>", re.IGNORECASE)

def markdown_to_html(md_text: str) -> str:
    # Render conservative HTML; no raw HTML passthrough
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
    # footer link to the web page
    full_html += f'\n<p><a href="{episode_url}">View this episode on the web</a></p>'

    # Trim for show notes (<description>); approximate by visible char count
    text_len = 0
    out = []
    in_tag = False
    for ch in full_html:
        if ch == "<":
            in_tag = True
        if not in_tag:
            text_len += 1
        out.append(ch)
        if ch == ">":
            in_tag = False
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
    # fallback: first episode cover
    for md in sorted(POSTS_DIR.glob("*.md")):
        fm, _ = parse_front_matter(md)
        cov = fm.get("cover_image")
        if cov:
            return abs_url(cfg["site_url"], cfg["baseurl"], cov)
    return abs_url(cfg["site_url"], cfg["baseurl"], "/assets/cover.jpg")

# ---------- main build ----------

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

    items_data = []  # (pub_dt, xml_string)

    posts = sorted(POSTS_DIR.glob("*.md"))
    if not posts:
        print("No posts found in _posts/")

    for md in posts:
        fm, body_md = parse_front_matter(md)
        pub_dt = compute_pub_dt(md, fm)

        # future-post filter
        if (not cfg["future"]) and pub_dt > datetime.now(timezone.utc):
            continue

        title = fm.get("title", md.stem)
        desc_short = fm.get("description", "")  # used as bold intro at top of notes
        cover = fm.get("cover_image")
        audio_url = fm.get("audio_url", "")

        date = md.name[:10]
        y, m, d = date.split("-")
        slug = md.stem[11:]
        folder = f"{date}-{slug}"

        # URLs
        page_url = abs_url(cfg["site_url"], cfg["baseurl"], f"/{y}/{m}/{d}/{slug}.html")
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
        body_with_intro = (f"**{desc_short}**\n\n" if desc_short else "") + (body_md or "")
        desc_notes_html, full_notes_html = make_notes_html(body_with_intro, page_url)

        # optional transcript link via Podcasting 2.0 (keeps raw transcript file, not pasted)
        tx = read_transcript(folder)

        # build <item>
        item = []
        item.append("  <item>")
        item.append(f"    <title>{html.escape(title)}</title>")
        item.append(f"    <link>{page_url}</link>")
        item.append(f"    <guid isPermaLink=\"true\">{page_url}</guid>")
        item.append(f"    <pubDate>{rfc2822_from_dt(pub_dt)}</pubDate>")

        # show notes (trimmed + full)
        item.append(f"    <description><![CDATA[{desc_notes_html}]]></description>")
        item.append(f"    <content:encoded><![CDATA[{full_notes_html}]]></content:encoded>")

        # per-episode artwork
        if cover_abs:
            item.append(f'    <itunes:image href="{cover_abs}"/>')

        # audio enclosure
        if audio_abs:
            length_attr = f' length="{enclosure_len}"' if (enclosure_len is not None) else ""
            item.append(f'    <enclosure url="{audio_abs}" type="audio/mpeg"{length_attr} />')

        # keep a short itunes:summary from description only
        if desc_short:
            item.append(f"    <itunes:summary>{html.escape(desc_short)}</itunes:summary>")

        # podcast:transcript
        if tx:
            tx_abs = abs_url(cfg["site_url"], cfg["baseurl"], f"/episodes/{folder}/transcript.txt")
            item.append(f'    <podcast:transcript url="{tx_abs}" type="text/plain" />')

        item.append("  </item>")
        items_data.append((pub_dt, "\n".join(item)))

    # sort items by pubDate DESC (newest first)
    items_data.sort(key=lambda x: x[0], reverse=True)
    items_xml = [xml for _, xml in items_data]

    # channel lastBuildDate
    last_build = items_data[0][0] if items_data else datetime.now(timezone.utc)

    # close channel+rss
    xml_out = []
    xml_out.append('<?xml version="1.0" encoding="UTF-8"?>')
    xml_out.append('<rss version="2.0"')
    xml_out.append('     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"')
    xml_out.append('     xmlns:content="http://purl.org/rss/1.0/modules/content/"')
    xml_out.append('     xmlns:atom="http://www.w3.org/2005/Atom"')
    xml_out.append('     xmlns:podcast="https://podcastindex.org/namespace/1.0">')
    xml_out.append('<channel>')
    xml_out.append(f'  <title>{html.escape(cfg["title"])}</title>')
    xml_out.append(f'  <link>{cfg["site_url"]}{cfg["baseurl"]}</link>')
    xml_out.append(f'  <language>{cfg["language"]}</language>')
    xml_out.append(f'  <itunes:author>{html.escape(cfg["author"])}</itunes:author>')
    xml_out.append(f'  <itunes:summary>{html.escape(cfg["description"])}</itunes:summary>')
    xml_out.append(f'  <description>{html.escape(cfg["description"])}</description>')
    xml_out.append(f'  <itunes:explicit>{cfg["explicit"]}</itunes:explicit>')
    xml_out.append(f'  <itunes:owner><itunes:name>{html.escape(cfg["owner_name"])}</itunes:name><itunes:email>{html.escape(cfg["owner_email"])}</itunes:email></itunes:owner>')
    xml_out.append(f'  <itunes:image href="{pick_channel_image(cfg)}"/>')
    xml_out.append(f'  <itunes:category text="{html.escape(cfg["category"])}"/>')
    xml_out.append(f'  <itunes:type>{html.escape(cfg["itunes_type"])}</itunes:type>')
    xml_out.append(f'  <atom:link href="{cfg["site_url"]}{cfg["baseurl"]}/podcast.xml" rel="self" type="application/rss+xml" />')
    xml_out.append(f'  <lastBuildDate>{rfc2822_from_dt(last_build)}</lastBuildDate>')
    xml_out.extend(items_xml)
    xml_out.append("</channel>")
    xml_out.append("</rss>\n")

    OUT_FILE.write_text("\n".join(xml_out), encoding="utf-8")
    print(f"Wrote {OUT_FILE.relative_to(ROOT)} with {len(items_xml)} item(s).")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Failed to build feed:", e)
        sys.exit(1)
