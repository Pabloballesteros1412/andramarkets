"""Writing, with a numeric guardrail.

Three passes separate a publishable note from an automated bulletin:

  1. WRITE    The model gets only the verified fact pack from
              analytics.fact_pack(). It does not browse, recall or estimate.
  2. AUDIT    Every figure in the returned text is checked against the fact
              pack: a percentage to within 0.01 points, a level to rounding
              (0.05%, or the stored value rounded to the decimals quoted).
  3. REWRITE  The text goes back with offending figures flagged. On a second
              failure the note ships with a warning in the email subject.

Net effect: a number never reaches print unless it is in the database.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field

from .universe import all_instruments

log = logging.getLogger("andra.narrative")

MODEL = os.getenv("ANDRA_MODEL", "claude-sonnet-5")
# How close a figure in the text must be to a value in the fact pack.
LEVEL_TOL = 0.0005     # levels and prices: 0.05% of the stored value
POINT_TOL = 0.01       # anything quoted in % (changes, yields): 0.01 points

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
    # Every model call of the note, failed attempts included: input and
    # output tokens and wall time spent waiting on the API.
    usage: dict = field(default_factory=lambda: {
        "input_tokens": 0, "output_tokens": 0, "model_seconds": 0.0, "calls": 0})


# A figure is read whole: 7,747.71 and 7747.71 are one number. The old
# pattern took at most three digits before a missing comma, so 7747.71 was
# audited as 774 and 7.71, two figures no fact pack holds. A sign only counts
# when it does not follow a digit, so 7-10 and 2026-10-21 hold no negatives.
_NUM = re.compile(
    r"(?<![\d.])((?:(?<!\d)[-+])?)((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?)"
    r"(\s*(?:%|per\s?cent\b|bps?\b|basis points?\b))?", re.I)

# Numbers that are part of a name or a fixed term, not figures: index names
# (S&P 500, Nikkei 225, ASX 200), tenors and look-backs (10-year, 200-day,
# 52-week) and curve shorthand (2s10s, 3m10y, 5y5y, 10y). They are removed
# before the audit. Left in, "S&P 500" failed the check whenever no figure in
# the fact pack happened to sit within 2% of 500.
_ALIASES = ("MidCap 400", "Midcap 400", "S&P 400", "S&P 600", "SmallCap 600",
            "Nasdaq-100", "Russell 1000", "Russell 3000", "Euro Stoxx 50",
            "Stoxx 50", "Stoxx 600", "FTSE 250", "Dow 30", "CSI 300",
            "Nikkei 225", "ASX 200", "Hang Seng 50")
_NAMES = re.compile("|".join(
    r"(?<![\w&])" + re.escape(n).replace(r"\ ", r"[\s-]") + r"(?!\w)"
    for n in sorted({i.name for i in all_instruments() if re.search(r"\d", i.name)}
                    | set(_ALIASES), key=len, reverse=True)), re.I)
_TERMS = re.compile(
    r"\b\d{1,3}[\s-](?:day|week|month|year|session)\b"   # 200-day, 10-year
    r"|\b\d{1,2}[smy]\d{1,2}[smy]s?\b"                     # 2s10s, 3m10y, 5y5y
    r"|\b\d{1,2}[my]\b", re.I)                              # 10y, 3m


def _strip_names(text: str) -> str:
    return _TERMS.sub(" ", _NAMES.sub(" ", text))


def _fact_values(facts: dict) -> list[float]:
    vals: list[float] = []

    def walk(o):
        if isinstance(o, dict):
            [walk(v) for v in o.values()]
        elif isinstance(o, list):
            [walk(v) for v in o]
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            vals.append(float(o))
    walk(facts)
    return vals


def _figures(text: str) -> list[tuple[str, float, bool, int, str]]:
    """(as written, value, signed, decimals quoted, unit: '%', 'bp' or '')."""
    out = []
    for m in _NUM.finditer(_strip_names(text)):
        sign, num, dec, unit = m.groups()
        unit = (unit or "").strip().lower()
        unit = "%" if unit.startswith(("%", "per")) else "bp" if unit else ""
        value = float(num.replace(",", "")) * (-1 if sign == "-" else 1)
        out.append((m.group(0).strip(), value, bool(sign), len(dec or ""), unit))
    return out


def _supported(n: float, signed: bool, decimals: int, unit: str,
               facts: list[float]) -> bool:
    # A bare integer up to 100 is a count, a day of the month or an hour (four
    # catalysts, 18 advancers, 9 Oct); a year is a year. Neither is checked.
    if not unit and decimals == 0 and (0 <= n <= 100 or 1900 <= n <= 2119):
        return True
    # A figure written with a sign must match the sign stored; one written
    # without ("fell 0.84%") may quote a negative value by its size.
    targets = facts if signed else [abs(v) for v in facts]
    eps = 1e-9
    if unit == "%":
        return any(abs(n - v) <= POINT_TOL + eps for v in targets)
    # Levels, prices, basis points and other ratios: within 0.05%, or the
    # stored value rounded half up to the decimals written (EUR/USD 1.123
    # quoted as 1.12, a 41.5bp spread as 42bp). A whole-number level must be
    # within 0.05%: 7,757 for 7,757.17 passes, 7,800 does not.
    if unit == "bp" or decimals >= 1:
        half_step = 0.5 * 10 ** -decimals
        if any(abs(n - v) <= half_step + eps for v in targets):
            return True
    return any(abs(n - v) <= LEVEL_TOL * abs(v) + eps for v in targets)


def audit(content: dict, facts: dict) -> list[str]:
    stored = _fact_values(facts)
    text = " ".join(v if isinstance(v, str) else " ".join(map(str, v))
                    for v in content.values())
    bad = [raw for raw, n, signed, dec, unit in _figures(text)
           if not _supported(n, signed, dec, unit, stored)]
    return sorted(set(bad))


MAX_TOKENS = int(os.getenv("ANDRA_MAX_TOKENS", "16000"))
# Required on every model call (CLAUDE.md). Without it the model can spend
# the whole token budget on a hidden thinking block and return no text: the
# reply comes back as blocks ['thinking'], stop max_tokens. That is how the
# 23 October 2026 note went out as tables only, after this was removed.
THINKING = {"type": "disabled"}

FIELDS = ("headline", "standfirst", "takeaways", "equities", "rates", "credit",
          "fx", "commodities", "volatility", "digital", "international",
          "correlation", "desk_view", "watching", "linkedin", "tiktok")
LIST_FIELDS = ("takeaways", "watching")


_TAG = re.compile(r"^\s*=+\s*(\w+)\s*=+\s*$", re.M)


def parse_reply(txt: str, fields=FIELDS, list_fields=LIST_FIELDS) -> dict:
    """Split a tagged reply into sections. Never raises on shape alone.
    `fields` names the sections kept (the weekly review has its own)."""
    txt = re.sub(r"```[a-z]*", "", txt).strip()
    marks = list(_TAG.finditer(txt))
    if not marks:
        raise ValueError(f"no section tags in reply ({len(txt)} chars): "
                         f"{txt[:300]!r}")

    out: dict = {}
    for i, m in enumerate(marks):
        name = m.group(1).strip().lower()
        if name not in fields:
            continue
        stop = marks[i + 1].start() if i + 1 < len(marks) else len(txt)
        body = txt[m.end():stop].strip()
        if not body:
            continue
        if name in list_fields:
            items = [re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", ln).strip()
                     for ln in body.splitlines() if ln.strip()]
            out[name] = [i for i in items if i]
        else:
            out[name] = re.sub(r"\n{3,}", "\n\n", body)

    if not out:
        raise ValueError(f"tags found but every section was empty: {txt[:300]!r}")
    missing = [f for f in fields if f not in out]
    if missing:
        log.warning("Reply is missing %d section(s): %s", len(missing),
                    ", ".join(missing))
    return out


def _metered(meter: dict | None, create, **kwargs):
    """client.messages.create, adding its tokens and time to meter."""
    t0 = time.monotonic()
    try:
        r = create(**kwargs)
    finally:
        if meter is not None:
            meter["model_seconds"] = round(meter["model_seconds"] + time.monotonic() - t0, 2)
            meter["calls"] += 1
    u = getattr(r, "usage", None)
    if meter is not None and u is not None:
        meter["input_tokens"] += int(getattr(u, "input_tokens", 0) or 0)
        meter["output_tokens"] += int(getattr(u, "output_tokens", 0) or 0)
    return r


def _call(client, messages: list[dict], meter: dict | None = None) -> dict:
    # Thinking explicitly disabled, no temperature (CLAUDE.md). A reply that
    # still carries no text or stops at the token ceiling is caught below and
    # counts as a failed attempt, so it is retried, never printed.
    r = _metered(meter, client.messages.create, model=MODEL, max_tokens=MAX_TOKENS,
                 system=SYSTEM, messages=messages, thinking=THINKING)

    txt = "".join(getattr(b, "text", "") for b in r.content
                  if b.type == "text").strip()
    if not txt:
        kinds = [b.type for b in r.content]
        raise ValueError(f"reply carried no text (blocks: {kinds}, "
                         f"stop: {r.stop_reason}).")
    if os.getenv("ANDRA_DEBUG_REPLY"):
        log.info("Raw reply, first 600 chars: %r", txt[:600])
    # A reply cut off by the token ceiling, or one that skips a section, is a
    # failed attempt, never a note: on 4 and 15 September such replies were
    # printed stopping mid-sentence with every later section missing.
    if r.stop_reason == "max_tokens":
        raise ValueError(f"reply hit the {MAX_TOKENS}-token ceiling and is "
                         f"truncated ({len(txt)} chars). Raise ANDRA_MAX_TOKENS.")
    content = parse_reply(txt)
    missing = [f for f in FIELDS if f not in content]
    if missing:
        raise ValueError(f"reply is incomplete: no {', '.join(missing)}.")
    return content


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
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())
    prompt = (f"{SCHEMA}\n\nVerified fact pack for the session. This is the only "
              f"admissible source of figures:\n\n"
              f"{json.dumps(facts, ensure_ascii=False, default=str)}")
    messages = [{"role": "user", "content": prompt}]

    content, bad, last_error = {}, [], None
    usage = Note({}).usage
    for attempt in range(1, max_attempts + 1):
        try:
            content = _call(client, messages, usage)
        except Exception as e:  # noqa: BLE001
            last_error = e
            log.warning("Attempt %d failed to produce a usable reply: %s", attempt, e)
            continue

        bad = audit(content, facts)
        if not bad:
            return Note(_complete(content), True, [], attempt, usage)

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
        return Note(_complete(content), False, bad, max_attempts, usage)
    err = RuntimeError(f"no usable reply after {max_attempts} attempts: {last_error}")
    err.usage = usage  # what the failed attempts cost, for the manifest
    raise err


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
