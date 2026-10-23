# CLAUDE.md

Instructions for Claude Code sessions working on this repository.

## Project

Andra Markets is a fully automated daily US market close research agent. It runs on GitHub Actions and emails its deliverables every trading day.

All project files live in `andramarkets-agent/`.

Deliverables produced on each run:
- 5-page A4 research note (PDF)
- 8-slide LinkedIn document carousel (1200x1500)
- 7-still TikTok photo carousel (1080x1440, 3:4)
- LinkedIn and TikTok captions (English)
- Voiceover script
- Verified-facts JSON
- FX analysis note (PDF, 800 to 1,200 words) and its JSON for the site's FX section (`fx_YYYYMMDD.json`)

Secrets (Anthropic API key, FRED key, SMTP settings) live in GitHub repository secrets. Never print, log, hardcode or commit them.

## Owner and workflow

- The owner works on Windows and edits files through the GitHub web editor, usually without a terminal.
- When handing code to the owner to paste, deliver complete files, one file at a time. No diffs, no partial snippets, no zip files.
- Never use em dashes (U+2014) or other smart punctuation in code, comments or strings. Windows converts them on paste and breaks Python with a SyntaxError. Use plain ASCII hyphens and quotes.
- State the expected last line of every delivered file so the owner can check the paste was not truncated.
- Debug by finding the root cause first. Do not iterate blindly with guess fixes.

## Known technical constraints

- Anthropic API: use plain `client.messages.create()` with no thinking parameter, no temperature, and `MAX_TOKENS=16000`. Otherwise the model can spend the whole budget on thinking and return no text.
- Parse model output with tagged section delimiters (for example `===headline===`), not JSON.
- Strip whitespace from API keys read from secrets. A leading space in the FRED key once silently dropped every rate series.
- Anchor all dates to New York time (`_ny_now()`), or the report pulls the previous day's data.
- Keep the session date and dedup guards that prevent duplicate or misdated emails from overlapping cron runs. The date reported on is the last NYSE session that closed at least 15 minutes ago in New York (`andra/session.py`); a scheduled run reports only the session that closed that day, or nothing. `.last_published` records the last session emailed, and any run for a session already recorded exits without sending. The workflow commits the marker back after each run.
- GitHub Actions free-tier scheduling can delay or skip runs. That is a platform limitation, not a code bug. Do not try to "fix" it in code.
- Layout: use continuous flow with `break-inside: avoid`, not `overflow: hidden`, to avoid clipped content.

## Brand and output rules

- Everything is published as "Andra Markets", never under a personal name.
- All published text is in English.
- Research note style: Inter on white (falling back to Helvetica Neue, then TeX Gyre Heros), Andra Markets masthead, KPI band, numbered sections, methodology and disclaimer.
- Red and green go on every figure that shows a rise or a fall, always with its + or - sign so colour is never the only cue. Labels and prose stay black.
- Do not change the visual design of any deliverable unless the task asks for it.

## Coding guidelines

Adapted from andrej-karpathy-skills (MIT, github.com/multica-ai/andrej-karpathy-skills).

### 1. Think before coding
- State assumptions explicitly. If a request has several reasonable readings, say which one you chose and why.
- If a simpler approach exists, say so.
- In interactive sessions, ask when genuinely unsure. In unattended or scheduled runs, do not stop to ask: pick the most reasonable reading, record the decision in your summary, and continue. Stop only before an action that cannot be undone.

### 2. Simplicity first
- Write the minimum code that solves the problem. No features, abstractions or configuration that were not requested.
- No error handling for impossible scenarios.
- If 200 lines could be 50, rewrite it.

### 3. Surgical changes
- Touch only what the task needs. Do not reformat, refactor or "improve" adjacent code.
- Match the existing style.
- If you notice unrelated problems or dead code, mention them; do not change them.
- Remove only the imports, variables and functions that your own change made unused.

### 4. Goal-driven execution
- Turn each task into a verifiable goal. For a bug: reproduce it first, then fix it, then confirm the fix.
- For multi-step work, write a short plan where each step has a check.
- Before finishing, verify the result (run it, open the output, or check it against the source data) and report what you verified.

## Safety

- Work on a branch and open a pull request. Never push directly to main.
- Never run the production workflow in a way that sends real emails, unless the task explicitly asks for it.
- Never commit generated outputs, caches or large data files.
