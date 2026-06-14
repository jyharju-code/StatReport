# StatReport

Give an **example report**, a **prompt**, or a **combination** of both, plus your **data** —
and StatReport returns a finished statistical report. It is the statistics-domain sibling of
[EditMyRaw](https://github.com/jyharju-code/EditMyRaw): same key handling, same GUI/CLI, same
"the model only *advises*" architecture — but instead of editing photos to match a reference
look, it writes reports to match a reference *report*.

## The one principle that makes it trustworthy

EditMyRaw treats the model as an advisor and **clamps every value it returns** to a safe range;
local code does the actual editing. StatReport applies the exact same discipline, which matters
even more here:

> **The model never produces a number.** R (or the built-in Python engine) computes every figure;
> the model only chooses the report *recipe* and writes the prose **around verified output**. A
> claim-checking QA pass then confirms that every number in the narrative traces back to a number
> the engine actually computed — and flags any that don't.

A hallucinated p-value is far worse than a slightly-off exposure. This design makes it impossible
for an invented statistic to slip into the report unnoticed.

## Workflows

| Workflow | What you give | What happens |
|---|---|---|
| **Prompt** | a text description + data | the model designs the report recipe from your description |
| **Example** | an example report + data | imitate the example's structure and tone, with your data |
| **Combination** | example + prompt + data | "this report's shape, but add a forecast" — both at once |

Two modes:
- **Faithful** — descriptive / relational analyses only; prose strictly from computed numbers.
- **Creative** — adds regression and forecasting, and a richer, more interpretive narrative.

When the example report is a **PDF or DOCX**, the file itself is handed to the multimodal model so
it can read the document's layout — the direct parallel to EditMyRaw feeding the reference image.

## What you need — and what's optional

**Out of the box you only need what the installer brings (a managed Python).** With just that,
StatReport produces full **HTML** reports with every statistic, table, and chart. R and Quarto are
*optional upgrades* — install them and StatReport uses them automatically; skip them and nothing
breaks. So if you share this with someone, the honest summary is: **"it works without anything
extra — install R and Quarto only if you want fancier tables and PDF/Word output."**

| Tier | What to install | What you get |
|---|---|---|
| **Out of the box** | nothing extra (installer brings Python) | HTML reports, all analyses, charts, QA grounding |
| **+ R** | `statreport setup-r` | richer tables (gtsummary, modelsummary, easystats `report`) |
| **+ Quarto** | [Quarto](https://quarto.org/) only — no LaTeX needed | polished **PDF** (via bundled Typst) and **DOCX** |

The format selector and `--format` always succeed: if PDF/DOCX tooling is missing, StatReport says so
in the run log and writes a self-contained HTML report instead — never an error, never a blank page.

## Two engines (it always produces a report)

| | Compute | Render |
|---|---|---|
| **Rich** (if installed) | **R** — ggplot2 + the broad stats ecosystem, preferring ready report tooling (`gtsummary`, `modelsummary`, easystats `report`, `janitor`) | **Quarto** / pandoc → PDF, DOCX, HTML |
| **Built-in** (always) | **Python** — pandas, matplotlib, statsmodels | self-contained **HTML** (PDF via WeasyPrint if present) |

`--engine auto` uses R when `Rscript` is on your PATH and falls back to Python otherwise. Either
engine writes the **same** `results.json`, so the narrative, QA, and rendering steps are identical.

The assembled **`.qmd` source is always saved next to the report** — re-render it and you get the
same report. Reproducibility is the structural win this domain has over photo editing.

## API key (stored locally, never committed)

There is **no hardcoded key**. Set it once in the GUI (**API key & models** panel): paste, click
**Save**, and it is written to `~/.statreport/config.json` (permissions `600`) — outside this repo.
Resolution order: GUI-saved key → `GEMINI_API_KEY` env var → none. With no key, **Dry run** still
produces a full report (neutral recipe + template prose, computed numbers, 100% grounded).

> If a key was ever shared in chat or logs, rotate it in Google AI Studio.

## Quick install (one line)

Fetches a managed Python and all dependencies via [uv](https://docs.astral.sh/uv/) and puts a
launcher on your Desktop. No pre-installed Python needed.

**macOS:**
```bash
curl -fsSL https://raw.githubusercontent.com/jyharju-code/StatReport/main/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/jyharju-code/StatReport/main/install.ps1 | iex
```

Then add a free [Gemini API key](https://aistudio.google.com/apikey) in the app's settings panel.

**Rich R engine (recommended):** the installer can set it up for you — re-run the one-liner with
`STATREPORT_WITH_R=1` and it installs R + pandoc (via Homebrew on macOS / winget on Windows) and the
R packages automatically:

```bash
STATREPORT_WITH_R=1 bash -c "$(curl -fsSL https://raw.githubusercontent.com/jyharju-code/StatReport/main/install.sh)"
```

Already have R? Just run `statreport setup-r` to install the packages
(`jsonlite`, `ggplot2`, `gtsummary`, `modelsummary`, easystats `report`, `janitor`, …). For polished
PDF/DOCX add [Quarto](https://quarto.org/) (`brew install --cask quarto`). Without any of this,
StatReport uses its built-in Python engine and renders self-contained HTML.

## Install from source (developers)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Run the GUI

Opens in a **native desktop window** (pywebview) — its own icon, shows in the app switcher,
closing the window quits the process:

```bash
statreport web          # native window  (or: statreport-web)
statreport web --browser   # old behaviour: open a browser tab instead
```

If no webview backend is available, it falls back to a browser tab automatically.

### A clickable app (macOS)

To get a real double-clickable **StatReport.app** (opens in a native window, shows in
Launchpad / Spotlight / the app switcher, closing the window quits it):

```bash
./make_app.sh           # builds ~/Applications/StatReport.app + a `statreport` CLI shim
```

The locally-built app uses the default applet icon; the branded icon ships with the
PyInstaller release build. (The `statreport` command itself only lives inside the venv —
`make_app.sh` symlinks it into `~/.local/bin` so it works from any terminal.)

## CLI

```bash
# Prompt workflow, HTML, Python engine, no key needed:
statreport report --data tests/sample/sales.csv --dry-run \
  --prompt "Quarterly sales review: trend, regional comparison, key drivers." --out out

# Imitate an example report:
statreport report --data sales.csv --example example_report.md --workflow example --out out

# Combination + creative (adds regression/forecast) + PDF (needs Quarto/pandoc):
statreport report --data sales.csv --example example.pdf --workflow combo \
  --mode creative --format pdf --out out

# Key:
statreport key --set "AIza..."   # save locally
statreport key --show            # masked status
statreport key --clear

# Rich R engine: install the R packages (needs R already on PATH):
statreport setup-r
```

## How it works

1. **Profile** the data locally (schema, types, missingness, summaries, a tiny sample) — only this
   compact profile is ever shown to the model, never the raw rows.
2. **Recipe** — the model returns a JSON report recipe (sections + analyses + tone), which is
   `bounded()` against reality: variables must be real columns, methods must be on the per-mode
   allowlist, charts/tables must be known kinds, sections are capped.
3. **Compute** — R/Quarto or the Python engine runs every analysis, saving figures and tables and
   writing `results.json` (the numbers).
4. **Narrate** — the model writes the prose **using only numbers present in `results.json`**.
5. **QA** — a claim-checker verifies every number in the narrative against the computed results; in
   creative mode it can run revision "sparring" rounds to fix ungrounded numbers.
6. **Render** — assemble narrative + figures + tables into a `.qmd`/markdown doc and render to
   HTML/PDF/DOCX. The source artifact is saved for re-rendering.

## Layout

```
src/statreport/
  config.py     secure local API-key store (GUI-managed)      [ported from EditMyRaw]
  data_io.py    load + profile tabular data (the "preview")
  profile.py    parse an example report -> structure/tone profile
  recipe.py     bounded report recipe (pydantic)               [analog of EditMyRaw recipe.py]
  gemini.py     advisor: recipe, grounded narrative, QA revision
  rcode.py      R/Quarto compute-script generator (rich engine)
  pyengine.py   pure-Python compute engine (always-available fallback)
  rengine.py    run compute (R/Python) + render (Quarto/pandoc/HTML)
  qa.py         claim-checker: every narrative number must exist in the results
  pipeline.py   orchestration                                  [analog of EditMyRaw pipeline.py]
  server.py     Flask browser GUI                              [ported]
  cli.py        command line
  web/          GUI (index.html, app.js, styles.css)
```

## License

MIT.
