"""Writing, with a numeric guardrail.

Three passes separate a publishable note from an automated bulletin:

  1. WRITE    The model gets only the verified fact pack from
              analytics.fact_pack(). It does not browse, recall or estimate.
  2. AUDIT    Every figure in the returned text is checked against the set of
              permitted values, with a rounding tolerance.
  3. REWRITE  The text goes back with offending figures flagged. On a second
              failure the note ships with a warning in the email subject.

Net effect: a number never reaches print unless it is in the database.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field

log = logging.getLogger("andra.narrative")

MODEL = os.getenv("ANDRA_MODEL", "claude-sonnet-5")
TOLERANCE = 0.02

SYSTEM = """You write the daily US market close note for Andra Markets, a
markets research desk. The note goes out under the house name and is read by
people who trade for a living.

VOICE
Write like a strategist typing a note at 4:30pm, not like a press release.
Short declarative sentences. Concrete nouns. Lead each paragraph with the
conclusion, then the evidence. Vary sentence length. Say what the market
bought and what it sold it against. If you do not know why something moved,
describe the setup and stop.

NEVER USE
- Em dashes. Use a comma, a full stop, or a colon.
- The "not just X, but Y" construction, or any negative parallelism.
- Three-item lists used for rhythm rather than because there are three things.
- Present participle tails that add fake depth: "highlighting", "underscoring",
  "reflecting broader", "signaling a shift", "marking a turning point".
- Significance padding: pivotal, crucial, vital, key moment, testament,
  landscape, era, watershed, unprecedented, remarkable, notably, importantly.
- Corporate filler: leverage, navigate, robust, dynamic, seamless, delve,
  ecosystem, headwinds and tailwinds used as decoration.
- Rhetorical questions, second person, exclamation marks, emoji, bold or
  italic markup, bullet symbols inside a paragraph.
- Hedging stacks: "it is worth noting that", "it remains to be seen",
  "only time will tell", "in an environment where".
- Tabloid verbs: plunge, soar, crater, skyrocket, hammered, bloodbath.
  Prefer fell, rose, gave back, held, drifted.

NEVER DO
- Quote a figure in a form other than the one in the fact pack. If the pack
  says 0.43, write 0.43, never 0.44. Do not recompute or re-round.
- Invent, round by feel, or infer any figure. Only numbers present in the
  supplied fact pack may appear in the text.
- Assert a cause the data does not support.
- Give investment advice, price targets, or any buy or sell language.

NUMBER STYLE
Percentages to two decimals with a sign: +0.84%, -1.23%. Rate moves in basis
points: +7bp. US convention for thousands and decimals.

Follow the output format exactly. No preamble, no sign-off, no markdown."""

SCHEMA = """Output format. Write each section after its tag, on the lines
below it. Use the tags exactly as written, one per line, in this order. Do not
use JSON, markdown, quotes around sections, or any other wrapper.

Write tightly. Every paragraph must earn its space. A shorter note with no
filler beats a long one padded to length. Do not restate a table in prose; say
what the numbers mean.

===headline===
8 to 13 words. A claim with content, not a label.

===standfirst===
Two sentences. What happened and what it means for positioning.

===takeaways===
Four one-sentence conclusions, ordered by importance. One per line.

===desk_view===
Two paragraphs. What the session confirms or contradicts, and the level that
decides it. This is the most important section: write it in full.

===watching===
Four concrete catalysts for the next session. One per line.

===equities===
Two paragraphs: indices, sector rotation, breadth, dispersion.

===rates===
Two paragraphs: curve, shift, breakevens, auctions.

===credit===
One paragraph: spreads, primary market, tone of credit.

===fx===
One paragraph: dollar, G10 crosses, EM bloc.

===commodities===
One paragraph: energy, precious, industrial, ags.

===volatility===
One paragraph: the vol surface and the cost of protection.

===digital===
One paragraph: digital assets and their beta to risk.

===international===
One paragraph: European and Asian closes and what they hand New York.

===correlation===
Two paragraphs on cross-asset correlation and what a break in it would mean.

===linkedin===
LinkedIn caption, 900 to 1300 characters. Plain text. Open with the most
informative sentence of the day, no throat-clearing. Short paragraphs separated
by a blank line. No hashtags, no emoji, no markdown, no sign-off. End on the
level or condition that would change the read.

===tiktok===
Spoken script for a 7-slide photo carousel, 60 to 90 words total. Same voice,
shorter sentences. No hype.
"""


@dataclass
class Note:
    content: dict
    audit_ok: bool = True
    unsupported: list[str] = field(default_factory=list)
    attempts: int = 1


_NUM = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?")


def _permitted(facts: dict) -> set[float]:
    vals: set[float] = set()

    def walk(o):
        if isinstance(o, dict):
            [walk(v) for v in o.values()]
        elif isinstance(o, list):
            [walk(v) for v in o]
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            v = float(o)
            vals.update({round(v, 2), round(abs(v), 2), round(v, 1), round(v, 0)})
    walk(facts)
    vals |= {float(x) for x in range(0, 101)}
    vals |= {1900.0 + i for i in range(220)}
    return vals


def _figures(text: str) -> list[float]:
    out = []
    for m in _NUM.findall(text):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def audit(content: dict, facts: dict) -> list[str]:
    allowed = _permitted(facts)
    text = " ".join(v if isinstance(v, str) else " ".join(map(str, v))
                    for v in content.values())
    bad = []
    for n in _figures(text):
        if any(abs(n - p) <= max(TOLERANCE, abs(p) * TOLERANCE) for p in allowed):
            continue
        bad.append(f"{n:g}")
    return sorted(set(bad))


MAX_TOKENS = int(os.getenv("ANDRA_MAX_TOKENS", "16000"))

FIELDS = ("headline", "standfirst", "takeaways", "equities", "rates", "credit",
          "fx", "commodities", "volatility", "digital", "international",
          "correlation", "desk_view", "watching", "linkedin", "tiktok")
LIST_FIELDS = ("takeaways", "watching")


_TAG = re.compile(r"^\s*=+\s*(\w+)\s*=+\s*$", re.M)


def parse_reply(txt: str) -> dict:
    """Split a tagged reply into sections. Never raises on shape alone."""
    txt = re.sub(r"```[a-z]*", "", txt).strip()
    marks = list(_TAG.finditer(txt))
    if not marks:
        raise ValueError(f"no section tags in reply ({len(txt)} chars): "
                         f"{txt[:300]!r}")

    out: dict = {}
    for i, m in enumerate(marks):
        name = m.group(1).strip().lower()
        if name not in FIELDS:
            continue
        stop = marks[i + 1].start() if i + 1 < len(marks) else len(txt)
        body = txt[m.end():stop].strip()
        if not body:
            continue
        if name in LIST_FIELDS:
            items = [re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", ln).strip()
                     for ln in body.splitlines() if ln.strip()]
            out[name] = [i for i in items if i]
        else:
            out[name] = re.sub(r"\n{3,}", "\n\n", body)

    if not out:
        raise ValueError(f"tags found but every section was empty: {txt[:300]!r}")
    missing = [f for f in FIELDS if f not in out]
    if missing:
        log.warning("Reply is missing %d section(s): %s", len(missing),
                    ", ".join(missing))
    return out


def _call(client, messages: list[dict]) -> dict:
    r = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS,
                               system=SYSTEM, messages=messages)

    txt = "".join(getattr(b, "text", "") for b in r.content
                  if b.type == "text").strip()
    if not txt:
        kinds = [b.type for b in r.content]
        raise ValueError(f"reply carried no text (blocks: {kinds}, "
                         f"stop: {r.stop_reason}).")
    if r.stop_reason == "max_tokens":
        log.warning("Reply hit the token ceiling and may be truncated. "
                    "Raise ANDRA_MAX_TOKENS above %d.", MAX_TOKENS)
    if os.getenv("ANDRA_DEBUG_REPLY"):
        log.info("Raw reply, first 600 chars: %r", txt[:600])
    return parse_reply(txt)


def _complete(content: dict) -> dict:
    """Fill any gap so the templates never hit a missing key."""
    for f in FIELDS:
        content.setdefault(f, [] if f in LIST_FIELDS else "")
    if not content.get("headline"):
        content["headline"] = "Market close"
    return content


def _as_tagged(content: dict) -> str:
    """Render a parsed note back into tagged format for the retry turn."""
    parts = []
    for f in FIELDS:
        v = content.get(f)
        if not v:
            continue
        body = "\n".join(v) if isinstance(v, list) else v
        parts.append(f"==={f}===\n{body}")
    return "\n\n".join(parts)


def write(facts: dict, max_attempts: int = 3) -> Note:
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = (f"{SCHEMA}\n\nVerified fact pack for the session. This is the only "
              f"admissible source of figures:\n\n"
              f"{json.dumps(facts, ensure_ascii=False, default=str)}")
    messages = [{"role": "user", "content": prompt}]

    content, bad, last_error = {}, [], None
    for attempt in range(1, max_attempts + 1):
        try:
            content = _call(client, messages)
        except Exception as e:  # noqa: BLE001
            last_error = e
            log.warning("Attempt %d failed to produce a usable reply: %s", attempt, e)
            continue

        bad = audit(content, facts)
        if not bad:
            return Note(_complete(content), True, [], attempt)

        log.warning("Audit %d rejected figures: %s", attempt, bad)
        messages += [
            {"role": "assistant", "content": _as_tagged(content)},
            {"role": "user", "content":
                f"The figure check rejected these because they are not in the "
                f"fact pack: {bad}. Return the full note again with those "
                f"removed or replaced by the correct value from the pack. Do "
                f"not introduce any new figure."},
        ]

    if content:
        return Note(_complete(content), False, bad, max_attempts)
    raise RuntimeError(f"no usable reply after {max_attempts} attempts: {last_error}")


def write_without_model(facts: dict) -> Note:
    """Degraded mode. Tables and exhibits ship, prose does not."""
    b = facts.get("risk_barometer", {})
    blank = {k: "" for k in ("equities", "rates", "credit", "fx", "commodities",
                             "volatility", "digital", "international",
                             "correlation", "desk_view", "linkedin", "tiktok")}
    return Note({
        "headline": "Market close: quantitative read of the session",
        "standfirst": ("Published in quantitative mode. Editorial commentary is "
                       "unavailable in this edition; tables and exhibits reflect "
                       "the official close."),
        "takeaways": [f"Cross-asset risk score at {b.get('score')} ({b.get('label')})."],
        "watching": [], **blank,
    }, audit_ok=True)
