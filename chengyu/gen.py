# chengyu/gen.py
import re, json
from openai import OpenAI
from .utils import normalize_chengyu

SYSTEM = (
    "You create short, conversational podcast episodes about Chinese 成语. "
    "Return ONLY valid JSON. No code fences."
)

# -------- A) pick a batch of candidate idioms --------
def pick_new_chengyu(model: str, batch_size: int = 20) -> list[str]:
    """Ask the model for a diverse list of idioms (characters only)."""
    client = OpenAI()
    prompt = f"""
Return a JSON object with a single key "list" whose value is an array of {batch_size}
well-known, mutually distinct Chinese 成语 (use CHINESE CHARACTERS only). No commentary.
Example:
{{ "list": ["画蛇添足","井底之蛙","对牛弹琴"] }}
"""
    resp = client.chat.completions.create(
        model=model,
        temperature=0.8,
        response_format={"type": "json_object"},
        messages=[
            {"role":"system","content":"Return JSON only."},
            {"role":"user","content":prompt}
        ]
    )
    data = json.loads(resp.choices[0].message.content)
    lst = data.get("list") or []
    return [s for s in lst if isinstance(s, str) and s.strip()]

# -------- B) generate full episode for a specific idiom --------
def gen_episode_for(show_name: str, model: str, chengyu: str) -> dict:
    client = OpenAI()
    STRUCT = f"""
Create a short, conversational episode for this EXACT Chinese 成语: {chengyu}

Follow this structure EXACTLY in the "script" field:
1) Intro: Start with: "Welcome to {show_name} — your quick summary on Chinese 成语." Add a one-sentence teaser. Add [break 1s].
2) Reveal: Say "The phrase is:" then the idiom in CHINESE CHARACTERS, followed by the pinyin.
3) Character breakdown: Each character with pinyin and meaning, each line ending with [break 0.5s].
4) Full idiom again: characters + literal & figurative meaning. Add [break 1s].
5) Origin story: 4–5 sentences. Start with "Here’s the story behind it:" then [break 1.5s], then the story, then [break 1.5s].
6) Three examples: For each, give Mandarin on one line and English on the next. Put [break 1s] after each pair.
7) Closing: Repeat the idiom in Chinese and the short English meaning; thank the listener and sign off with: "Thanks for listening to {show_name}! See you next time for another idiom." End with [break 1s].

Important:
- Keep the idiom in CHINESE CHARACTERS in the script (use pinyin only where asked).
- Use [break 0.5s], [break 1s], [break 1.5s]. No SSML. Slightly slower tone.

Return JSON with keys:
{{
  "chengyu": "<characters>",
  "pinyin": "<pinyin with tone marks>",
  "gloss": "<literal + figurative meaning in one short line>",
  "teaser": "<one-sentence teaser>",
  "script": "<full episode script with [break] tags>"
}}
"""
    resp = client.chat.completions.create(
        model=model,
        temperature=0.7,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": STRUCT}
        ]
    )
    data = json.loads(resp.choices[0].message.content)
    for k in ("chengyu","pinyin","gloss","teaser","script"):
        assert isinstance(data.get(k), str) and data[k].strip()
    return data

# -------- C) strict unique wrapper (no duplicates ever) --------
def gen_unique_episode_strict(show_name: str, model: str, forbidden: set[str],
                              batch_size: int = 20, max_rounds: int = 20) -> dict:
    """Never return a duplicate: batch-pick → local filter → generate for chosen idiom → re-check."""
    forbid_norm = {normalize_chengyu(x) for x in forbidden}
    last_err = None
    for _ in range(max_rounds):
        candidates = pick_new_chengyu(model, batch_size=batch_size)
        for cand in candidates:
            if normalize_chengyu(cand) not in forbid_norm:
                data = gen_episode_for(show_name, model, cand)
                if normalize_chengyu(data["chengyu"]) in forbid_norm:
                    last_err = f"Model returned duplicate after selection: {data['chengyu']}"
                    continue
                return data
        last_err = f"No unseen idioms in batch of {len(candidates)}."
    raise RuntimeError(last_err or "Failed to find an unseen idiom")

# -------- D) pretty Markdown formatting --------
def script_to_markdown(chengyu: str, pinyin: str, gloss: str, teaser: str, script: str, model: str) -> str:
    """Format the raw script into structured Markdown (no top-level H1)."""
    client = OpenAI()
    cleaned = re.sub(r"\[break\s*[0-9.]+s\]", " ", script or "")

    SYS = ("You are a precise formatter. Turn a 成语 podcast script "
           "into clean, concise Markdown sections. No code fences.")
    INSTR = f"""
Goal: Reformat "{chengyu} ({pinyin})" into Markdown (no H1; page already has title).

Rules:
- Use '##' for section headings only.
- Characters section = Markdown table with columns: 字 | Pinyin | Meaning.
- Examples: bullet list; each item 'Chinese<br>English'.
- No SSML or [break] tags.

Output exactly:

> {teaser}

## Overview
{gloss}

## Phrase
**{chengyu}** — {pinyin}

## Characters
(Table with one row per character)

## Origin
(4–5 sentences.)

## Examples
- Chinese sentence<br>English translation
- Chinese sentence<br>English translation
- Chinese sentence<br>English translation

## Closing
(Repeat {chengyu} and give a one-line meaning/sign-off.)
"""
    resp = client.chat.completions.create(
        model=model,
        temperature=0.3,
        messages=[
            {"role":"system","content":SYS},
            {"role":"user","content":INSTR},
            {"role":"user","content":cleaned}
        ]
    )
    md = resp.choices[0].message.content.strip()
    # Strip accidental code fences
    return re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", md, flags=re.S|re.I)
