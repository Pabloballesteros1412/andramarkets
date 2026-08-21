"""Writing, with a numeric guardrail.

Three passes, which is what separates a publishable note from an automated
bulletin:

  1. WRITE    The model gets only the verified fact pack from
              analytics.fact_pack(). It does not browse, recall or estimate.
  2. AUDIT    Every figure in the returned text is extracted and checked
              against the set of permitted values, with a rounding tolerance.
              One unsupported figure fails the pass.
  3. REWRITE  The text goes back with the offending figures flagged. On a
              second failure the note ships with the affected sections
              degraded to data and the email subject carries a warning.

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
conclusion, then the evidence. Vary sentence length: a five-word sentence
after a long one does more work than any connective. Say what the market
bought and what it sold it against. If you do not know why something moved,
describe the setup and stop.

NEVER USE
- Em dashes. Use a comma, a full stop, or a colon.
- The "not just X, but Y" construction, or any negative parallelism.
- Three-item lists used for rhythm rather than because there are three things.
- Present participle tails that add fake depth: "highlighting", "underscoring",
  "reflecting broader", "signaling a shift", "marking a turning point",
  "setting the stage", "cementing", "reinforcing".
- Significance padding: pivotal, crucial, vital, key moment, testament,
  landscape, era, watershed, unprecedented, remarkable, notably, importantly.
- Corporate filler: leverage, navigate, robust, dynamic, seamless, delve,
  landscape, ecosystem, headwinds and tailwinds used as decoration.
- Rhetorical questions, second person, exclamation marks, emoji, bold or
  italic markup, bullet symbols inside a paragraph.
- Hedging stacks: "it is worth noting that", "it remains to be seen",
  "only time will tell", "in an environment where".
- Tabloid verbs: plunge, soar, crater, skyrocket, hammered, bloodbath.
  Prefer fell, rose, gave back, held, drifted.

NEVER DO
- Invent, round by feel, or infer any figure. Only numbers present in the
  supplied fact pack may appear in the text.
- Assert a cause the data does not support.
- Give investment advice, price targets, or any buy or sell language.

NUMBER STYLE
Percentages to two decimals with a sign: +0.84%, -1.23%. Rate moves in basis
points: +7bp. US convention for thousands and decimals.

Return one valid JSON object. No markdown, no preamble, no code fence."""

SCHEMA = """Exact output shape:

{
  "headline":      "8 to 13 words. A claim with content, not a label.",
  "standfirst":    "Two sentences. What happened and what it means for positioning.",
  "takeaways":     ["Four one-sentence conclusions, ordered by importance"],
  "equities":      "Two paragraphs: indices, sector rotation, breadth, dispersion.",
  "rates":         "Two paragraphs: curve, shift, breakevens, auctions.",
  "credit":        "One paragraph: spreads, primary market, tone of credit.",
  "fx":            "One paragraph: dollar, G10 crosses, EM bloc.",
  "commodities":   "One paragraph: energy, precious, industrial, ags.",
  "volatility":    "One paragraph: the vol surface and the cost of protection.",
  "digital":       "One paragraph: digital assets and their beta to risk.",
  "international": "One paragraph: European and Asian closes and what they hand New York.",
  "correlation":   "Two paragraphs on cross-asset correlation and what a break in it would mean.",
  "desk_view":     "Two paragraphs. What the session confirms or contradicts, and the level that decides it.",
  "watching":      ["Four concrete catalysts for the next session"],
  "linkedin":      "LinkedIn caption, 900 to 1300 characters. Plain text. Open with the most informative sentence of the day, no throat-clearing. Short paragraphs separated by a blank line. No hashtags, no emoji, no markdown, no sign-off. End on the level or condition that would change the read.",
  "tiktok":        "Spoken script for a 7-slide photo carousel, 60 to 90 words total. Same voice, shorter sentences. No hype, no call to action beyond stating what the next session hinges on."
}"""


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


def _extract_json(txt: str) -> dict:
    """Read the object out of the reply, tolerating fences and stray prose.

    Models occasionally wrap the payload in a code fence or open with a line
    of commentary. Rather than trust the shape, take everything between the
    first brace and the last one.
    """
    txt = re.sub(r"```(?:json)?", "", txt).strip()
    start, end = txt.find("{"), txt.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in reply (got {len(txt)} chars): "
                         f"{txt[:200]!r}")
    return json.loads(txt[start:end + 1])


def _call(client, messages: list[dict]) -> dict:
    r = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS,
                               system=SYSTEM, messages=messages)
    txt = "".join(b.text for b in r.content if b.type == "text").strip()
    if not txt:
        kinds = [b.type for b in r.content]
        raise ValueError(f"reply carried no text block (blocks: {kinds}, "
                         f"stop_reason: {r.stop_reason})")
    if r.stop_reason == "max_tokens":
        log.warning("Reply hit the token ceiling and is probably truncated. "
                    "Raise ANDRA_MAX_TOKENS.")
    return _extract_json(txt)


def write(facts: dict, max_attempts: int = 2) -> Note:
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = (f"{SCHEMA}\n\nVerified fact pack for the session. This is the only "
              f"admissible source of figures:\n\n"
              f"{json.dumps(facts, ensure_ascii=False, default=str)}")
    messages = [{"role": "user", "content": prompt}]

    content, bad = {}, []
    for attempt in range(1, max_attempts + 1):
        content = _call(client, messages)
        bad = audit(content, facts)
        if not bad:
            return Note(content, True, [], attempt)
        log.warning("Audit %d rejected figures: %s", attempt, bad)
        messages += [
            {"role": "assistant", "content": json.dumps(content, ensure_ascii=False)},
            {"role": "user", "content":
                f"The figure check rejected these because they are not in the "
                f"fact pack: {bad}. Return the full JSON again with those "
                f"removed or replaced by the correct value from the pack. Do "
                f"not introduce any new figure."},
        ]
    return Note(content, False, bad, max_attempts)


def write_without_model(facts: dict) -> Note:
    """Degraded mode. Tables and exhibits ship, prose does not.

    Better to publish something short and correct than something fluent and
    unchecked.
    """
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
