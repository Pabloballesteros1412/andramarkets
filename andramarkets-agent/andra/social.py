"""Post copy for LinkedIn and TikTok.

LinkedIn renders no markdown. Emphasis comes from Unicode sans-bold, which
LinkedIn also indexes for search. Only the first ~210 characters show before
the "see more" fold, so the opening line has to carry the day's most useful
fact rather than a warm-up.
"""
from __future__ import annotations

import re

LIMIT = 2900
FOLD = 210

_B = {ord(c): chr(0x1D5D4 + i) for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
_B.update({ord(c): chr(0x1D5EE + i) for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")})
_B.update({ord(c): chr(0x1D7EC + i) for i, c in enumerate("0123456789")})

HASHTAGS = ("#markets #equities #ratesmarket #macro #trading #investing "
            "#marketclose #AndraMarkets")

TIKTOK_HASHTAGS = ("#markets #stocks #investing #finance #marketclose "
                   "#stockmarket #macro #trading")


def bold(text: str) -> str:
    return "".join(_B.get(ord(c), c) for c in text)


def linkedin_caption(note, ctx: dict) -> str:
    body = (note.content.get("linkedin") or "").strip()
    if not body:
        body = _fallback(note)
    header = bold(f"US MARKET CLOSE / {ctx['date_short'].upper()}")
    tail = ("Full note in the attached document.\n\n"
            "Information only. Not investment advice.")
    post = f"{header}\n\n{body}\n\n{tail}\n\n{HASHTAGS}"
    return re.sub(r"\n{3,}", "\n\n", post)[:LIMIT]


def tiktok_caption(note, ctx: dict) -> str:
    script = (note.content.get("tiktok") or "").strip()
    hook = note.content.get("headline", "US market close")
    lead = script.split(".")[0].strip() if script else hook
    return f"{lead}. Full breakdown in the slides.\n\n{TIKTOK_HASHTAGS}"[:2200]


def tiktok_script(note) -> str:
    return (note.content.get("tiktok") or "").strip()


def _fallback(note) -> str:
    c = note.content
    points = "\n\n".join(c.get("takeaways", [])[:4])
    return f"{c.get('standfirst','')}\n\n{points}"


def check(post: str) -> dict:
    """Pre-flight checks, including the AI tells worth catching."""
    visible = post[:FOLD]
    tells = [t for t in ("—", " – ", "not just", "underscor", "highlight",
                         "pivotal", "crucial", "testament", "landscape",
                         "delve", "it's worth noting", "in today's")
             if t.lower() in post.lower()]
    return {
        "characters": len(post),
        "within_limit": len(post) <= 3000,
        "hook": visible.split("\n")[0][:120],
        "hook_has_figure": bool(re.search(r"\d", visible)),
        "no_emoji": not re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", post),
        "style_flags": tells,
        "hashtags": len(re.findall(r"#\w+", post)),
    }
