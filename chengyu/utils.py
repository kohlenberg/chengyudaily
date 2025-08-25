import re, unicodedata, subprocess

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.U).strip().lower()
    text = re.sub(r"[-\s]+", "-", text, flags=re.U)
    return text or "episode"

def normalize_chengyu(s: str) -> str:
    """Canonicalize for dedupe: normalize width, drop ASCII punctuation/spaces."""
    s = s or ""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[!-~]", "", s)  # strip ASCII punct
    return s

def run(cmd, cwd=None, hide_token=False):
    display = " ".join(["***" if hide_token and "@" in str(x) else str(x) for x in cmd])
    print("+", display)
    subprocess.check_call(cmd, cwd=cwd)
