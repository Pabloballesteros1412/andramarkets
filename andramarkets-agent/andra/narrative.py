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
  "reflecting broader", "signaling a shift", "marking a turning
