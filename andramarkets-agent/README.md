# Andra Markets — daily market close agent

Builds an institutional close note every session, twenty minutes after the New
York bell, and emails it ready to publish.

Per run:

| File | Use |
|---|---|
| `AndraMarkets_Close_YYYYMMDD.pdf` | A4 research note, 5 pages |
| `AndraMarkets_LinkedIn_YYYYMMDD.pdf` | 8-page carousel, upload as a LinkedIn **Document** post |
| `tiktok_YYYYMMDD/*.png` | 7 stills at 1080×1920, upload as a TikTok **photo** post |
| `linkedin_caption_YYYYMMDD.txt` | Caption, ready to paste |
| `tiktok_caption_YYYYMMDD.txt` | Caption plus voiceover script |
| `facts_YYYYMMDD.json` | Verified fact pack. Traceability and archive |
| `manifest_YYYYMMDD.json` | Edition, figure check result and rejected figures, writing mode |

---

## 1 · Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env          # fill in
python run_daily.py --demo --no-mail
```

**Fonts.** The note is set in Inter, falling back to Helvetica Neue and then to
TeX Gyre Heros. On Linux: `sudo apt install fonts-texgyre fonts-liberation2`.
For the intended result, install Inter from rsms.me/inter and it will be picked
up automatically.

**Email.** With Gmail you need an app password. The account password will not
authenticate over SMTP.

---

## 2 · Schedule

```bash
mkdir -p logs && crontab deploy/crontab.txt
```

Also included: `deploy/Dockerfile` and `.github/workflows/daily-close.yml`,
which runs on its own every weekday at 20:30 and 21:30 UTC (4:30 pm ET in
summer and in winter). Actions schedules in UTC, so both DST windows are
declared. A scheduled run reports only the session that closed that day in
New York, so the firing that lands before the close (20:30 UTC in winter)
stops without reporting yesterday's session, and the one after the note
went out stops on the dedup marker. A manual run can still catch up a missed
session. Run workflow
still works by hand; tick resend to send a session again.

**Monitoring.** The Run monitoring workflow opens an issue titled
"Missed close note: <date>" when a scheduled run fails (with the failed step
and the end of its log), and at 22:45 UTC on any NYSE trading day whose note
is not in the archive by then. One issue per date; it is closed on its own if
the note comes out after all. No email. `python monitor.py check --date
YYYY-MM-DD --dry-run` prints what it would post.

---

## 3 · Layout

```
run_daily.py          orchestration and market calendar
andra/
  universe.py         what is covered, one block per asset class
  data.py             ingestion, swappable provider, quality control
  analytics.py        risk score, breadth, curve, dispersion, correlation
  narrative.py        writing with Claude plus the figure audit
  charts.py           eleven exhibits on the house palette
  render.py           HTML/CSS to PDF and PNG via Chromium
  social.py           captions, Unicode emphasis, pre-flight checks
  mailer.py           SMTP delivery
templates/
  styles.css          design system
  report.html.j2      A4 note
  linkedin.html.j2    1200×1500 carousel
  tiktok.html.j2      1080×1920 stills
```

### The figure guardrail

An automated bulletin becomes a publishable note when it stops inventing
numbers. Three passes enforce it:

1. **Write.** The model receives only the fact pack from
   `analytics.fact_pack()`. It does not browse, recall or estimate.
2. **Audit.** Every figure in the returned text is extracted and matched
   against the permitted set with a rounding tolerance. One unsupported figure
   fails the pass.
3. **Rewrite.** The text goes back with the offending figures flagged. On a
   second failure the note ships with a warning in the email subject and a
   control note in the disclaimer.

If the API is unreachable, `write_without_model()` publishes tables and
exhibits with no prose. Short and correct beats fluent and unchecked.

### Voice

`narrative.py` carries an explicit blocklist: no em dashes, no "not just X but
Y", no three-item lists used for rhythm, no participle tails
("underscoring", "highlighting"), no significance padding ("pivotal",
"crucial", "testament", "landscape"), no tabloid verbs ("plunge", "soar"). The
pre-flight check in `social.py` flags any that slip through and prints them in
the email.

### Providers

| Source | Covers | Cost |
|---|---|---|
| Yahoo | global equities, FX, commodities, volatility, digital | free |
| FRED | Treasury curve, breakevens, real yields | free, needs a key |
| `bloomberg` stub | global sovereigns, CDX, iTraxx | terminal |

`data.py` exposes one contract (`MarketFrame`), so wiring blpapi or Refinitiv
touches `_bloomberg` and the `src` field only. Nothing downstream sees a vendor
symbol. Until a terminal is connected, global sovereigns and cash credit
spreads print as n/a or as listed-vehicle proxies, with the caveat printed in
the note itself. Nothing is estimated.

---

## 4 · Design

No blue anywhere. Colour is reserved for data.

| Token | Hex | Use |
|---|---|---|
| Ink | `#0E0E0E` | headlines, rules, wordmark |
| Text | `#2B2B2B` | body |
| Muted | `#767676` | labels, secondary |
| Rule | `#D2D2D2` | hairlines |
| Panel | `#F5F5F5` | callouts |
| Gain | `#12684A` | positive data only |
| Loss | `#9C2A22` | negative data only |

Grotesque sans throughout, tabular figures, half-point rules, a millimetre
grid, no rounded corners. No justified text, no drop caps, no running prose
columns. Multi-series charts run on a greyscale ramp anchored by black rather
than a rainbow.

---

## 5 · Publishing

The email opens with the LinkedIn caption in plain text, then the TikTok
caption and script, then pre-flight: character count, what is visible before
the "see more" fold, hashtag count, figure-check result, style flags, risk
score, missing series.

- **LinkedIn:** Create post → Document → upload the carousel → paste the caption.
- **TikTok:** Upload → Photo → add the PNGs in order → paste the caption. The
  voiceover script is there if you record over the slides.

---

## 6 · Extensions

- **Economic calendar.** `run_daily.py` reads `calendar.json` if present. Wire
  Trading Economics or Econoday and section 13 fills itself.
- **Direct posting.** Both platforms have APIs. Left out on purpose: read the
  note before it goes out under the house name.
- **History.** Every run's report PDF, `facts_*.json`, `note_*.json` and
  `series_*.json` are kept for good as a release in this private repo, tagged
  `archive-YYYY-MM-DD`, one asset per file per run (`<file>_r<run id>`).
  `archive.py` does it after each run; the Archive backfill workflow copies
  every artifact that has not expired yet (artifacts last 90 days). After a
  few months you can feed prior sessions to the writer for narrative
  continuity.
- **Full index breadth.** The watchlist is 26 mega caps today. Expanding to the
  full S&P 500 improves breadth and dispersion at the cost of download time.

---

## 7 · Caveats

- The note is informational and carries a disclaimer. Publishing anything that
  looks like investment advice under a brand has regulatory implications that
  vary by jurisdiction. Worth checking before scaling.
- Yahoo offers no SLA and occasionally returns incomplete series. Quality
  control catches it and prints the count in the methodology section, but check
  the n/a count in the email.
- The figure audit guarantees the numbers are traceable. It does not guarantee
  the interpretation is right. Read the note before you post it.
