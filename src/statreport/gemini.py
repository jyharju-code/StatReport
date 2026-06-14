"""
gemini.py — Gemini as an ADVISOR (recipe + prose), never as a calculator.

Direct sibling of EditMyRaw's gemini.py:
  * EditMyRaw: vision -> bounded JSON *recipe*; local code applies it.
  * StatReport: example + data profile -> bounded JSON *report recipe*; the R /
    Python engine computes the numbers; Gemini then writes the prose around those
    verified numbers only.

build_recipe()     : (example, data profile, prompt) -> ReportRecipe (bounded).
write_narrative()  : (recipe, computed results) -> grounded markdown per section.
revise_narrative() : fix the numbers QA flagged (the "sparring" loop).

Multimodal bonus: when the example report is a PDF/DOCX, the file itself is handed
to the model to read its layout — the exact parallel to feeding the reference image.
Uses the official google-genai SDK. The key comes from config (GUI/env), never hardcoded.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from .config import Settings
from .recipe import ALL_METHODS, FAITHFUL_METHODS, Mode, ReportRecipe, neutral_recipe

# --- structured-output schemas (OpenAPI subset the SDK accepts) ---
_ANALYSIS = {
    "type": "object",
    "properties": {
        "method": {"type": "string"},
        "variables": {"type": "array", "items": {"type": "string"}},
        "group_by": {"type": "string"},
        "time_var": {"type": "string"},
        "chart": {"type": "string"},
        "table": {"type": "string"},
    },
    "required": ["method", "variables"],
}

RECIPE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "audience": {"type": "string"},
        "tone": {"type": "string"},
        "language": {"type": "string"},
        "summary": {"type": "boolean"},
        "diagnosis": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "heading": {"type": "string"},
                    "narrative": {"type": "boolean"},
                    "description": {"type": "string"},
                    "analysis": _ANALYSIS,
                },
                "required": ["id", "heading", "analysis"],
            },
        },
    },
    "required": ["title", "tone", "language", "sections"],
}

NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "markdown": {"type": "string"}},
                "required": ["id", "markdown"],
            },
        },
    },
    "required": ["sections"],
}

_MAX_ATTACH_BYTES = 18 * 1024 * 1024


class GeminiClient:
    def __init__(self, settings: Settings):
        if not settings.api_key:
            raise RuntimeError("No Gemini API key set. Add one in Settings, or use Dry run.")
        from google import genai
        self._settings = settings
        self._client = genai.Client(api_key=settings.api_key)

    # ------------------------------------------------------------------ #
    # 1) recipe
    # ------------------------------------------------------------------ #
    def build_recipe(self, data_profile, report_profile, prompt: str, mode: Mode,
                     workflow: str) -> ReportRecipe:
        from google.genai import types
        contents: list = []
        if report_profile is not None and workflow in ("example", "combo"):
            attached = self._maybe_attach(report_profile, types)
            if attached is not None:
                contents.append(attached)
        contents.append(build_recipe_prompt(data_profile, report_profile, prompt, mode, workflow))

        response = self._client.models.generate_content(
            model=self._settings.model, contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=RECIPE_SCHEMA),
        )
        columns = data_profile.column_names
        try:
            payload = json.loads(response.text)
            recipe = ReportRecipe.model_validate(payload)
            return recipe.bounded(columns, mode)
        except Exception:
            rec = neutral_recipe(columns, mode, prompt,
                                 numeric=data_profile.numeric,
                                 categorical=data_profile.categorical,
                                 datetime=data_profile.datetime)
            rec.diagnosis = "LLM recipe could not be parsed; used a neutral recipe."
            return rec

    def _maybe_attach(self, report_profile, types):
        try:
            if not report_profile.can_attach:
                return None
            if os.path.getsize(report_profile.raw_path) > _MAX_ATTACH_BYTES:
                return None
            data = Path(report_profile.raw_path).read_bytes()
            return types.Part.from_bytes(data=data, mime_type=report_profile.mime)
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # 2) narrative — grounded in computed numbers only
    # ------------------------------------------------------------------ #
    def write_narrative(self, recipe: ReportRecipe, results: dict,
                        report_profile, mode: Mode) -> Dict[str, str]:
        from google.genai import types
        prompt = build_narrative_prompt(recipe, results, report_profile, mode)
        response = self._client.models.generate_content(
            model=self._settings.narrative_model, contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=NARRATIVE_SCHEMA,
                temperature=0.4),
        )
        return _parse_narrative(response.text)

    # ------------------------------------------------------------------ #
    # 3) revise — the sparring loop fixing QA-flagged numbers
    # ------------------------------------------------------------------ #
    def revise_narrative(self, recipe: ReportRecipe, results: dict,
                         narrative: Dict[str, str], issues: List[dict],
                         round_i: int) -> Dict[str, str]:
        from google.genai import types
        flagged = "\n".join(f"- section '{i['section']}': unverified number "
                            f"{i['value']} in \"{i['context']}\"" for i in issues[:20])
        prompt = (
            "You previously wrote this report narrative, but the QA check found numbers "
            "that do NOT appear in the computed results. Rewrite the affected sections so "
            "every number is one that exists in the results JSON; if a figure is not in the "
            "results, state it qualitatively WITHOUT a number. Keep everything else.\n\n"
            f"Sparring round {round_i + 1}.\n\nFLAGGED:\n{flagged}\n\n"
            f"RESULTS (the only allowed source of numbers):\n{_results_for_model(results)}\n\n"
            f"CURRENT NARRATIVE:\n{json.dumps(narrative, ensure_ascii=False)}")
        response = self._client.models.generate_content(
            model=self._settings.narrative_model, contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=NARRATIVE_SCHEMA,
                temperature=0.2),
        )
        revised = _parse_narrative(response.text)
        merged = dict(narrative)
        merged.update({k: v for k, v in revised.items() if v})
        return merged


# --------------------------------------------------------------------------- #
# prompt builders
# --------------------------------------------------------------------------- #
def build_recipe_prompt(data_profile, report_profile, prompt: str, mode: Mode,
                        workflow: str) -> str:
    methods = sorted(FAITHFUL_METHODS if mode == Mode.faithful else ALL_METHODS)
    example_block = ""
    if report_profile is not None and workflow in ("example", "combo"):
        example_block = ("\nEXAMPLE REPORT TO IMITATE (structure & tone):\n"
                         + report_profile.skeleton_text() + "\n")
    prompt_block = ""
    if prompt and workflow in ("prompt", "combo"):
        prompt_block = f"\nUSER REQUEST:\n{prompt}\n"
    mode_line = ("FAITHFUL mode: descriptive/relational analyses only; keep it conservative."
                 if mode == Mode.faithful else
                 "CREATIVE mode: you may add regression and timeseries_forecast and richer framing.")

    return f"""
You are planning a statistical report. Return a JSON "report recipe": a title, tone, language,
and an ordered list of sections. Each section has a heading, a one-line `description` of what its
prose should convey, and an `analysis` that the engine will run.

Available analysis methods: {", ".join(methods)}.
Chart kinds: none, bar, line, scatter, hist, box, heatmap. Table kinds: none, summary, model, crosstab, head.

Rules:
- `variables`, `group_by`, and `time_var` MUST be exact column names from the data dictionary below
  (use "" for group_by/time_var when not needed).
- Choose methods that fit the column types. comparison needs a numeric variable + a categorical group_by.
  correlation/regression need >=2 numerics. trend/timeseries_forecast want a datetime time_var.
- Aim for 4-9 focused sections. Set `language` to match the user's request or the example report.
- {mode_line}
- Do NOT compute any numbers yourself — only specify what to analyse. The engine computes; you plan.

DATA DICTIONARY:
{data_profile.data_dictionary_text()}
{example_block}{prompt_block}
Return JSON only, matching the provided schema.
""".strip()


def build_narrative_prompt(recipe: ReportRecipe, results: dict, report_profile,
                           mode: Mode) -> str:
    tone_example = ""
    if report_profile is not None and report_profile.tone_sample:
        tone_example = ("\nMatch the WRITING TONE of this example excerpt:\n\"\"\""
                        + report_profile.tone_sample[:900] + "\"\"\"\n")
    summary_line = ("Also write an `summary`: a 3-5 sentence executive summary."
                    if recipe.summary else "Leave `summary` empty.")
    return f"""
You are writing the prose of a statistical report titled "{recipe.title}".
Write in language code "{recipe.language}", tone "{recipe.tone}", for audience "{recipe.audience}".

ABSOLUTE RULES (this is what makes the report trustworthy):
1. You may ONLY state a numeric figure if that exact number appears in the RESULTS for that section
   (in its `numbers` or `summary`). NEVER invent, round-trip, estimate, or extrapolate a number.
2. If you want to mention something not quantified in the results, describe it qualitatively
   (e.g. "the largest segment", "rose over the period") with NO number.
3. One short markdown passage per section id below. Do not restate the heading. Do not include
   tables or images — those are added automatically. {summary_line}
{tone_example}
SECTIONS TO WRITE (id -> what it should convey):
{_sections_brief(recipe)}

RESULTS (the ONLY allowed source of numbers):
{_results_for_model(results)}

Return JSON only, matching the provided schema.
""".strip()


def _sections_brief(recipe: ReportRecipe) -> str:
    return "\n".join(f"- {s.id}: {s.heading} — {s.description or s.analysis.method}"
                     for s in recipe.sections)


def _results_for_model(results: dict) -> str:
    slim = {"dataset": results.get("dataset", {}), "sections": {}}
    for sid, sec in results.get("sections", {}).items():
        slim["sections"][sid] = {
            "heading": sec.get("heading"), "method": sec.get("method"),
            "ok": sec.get("ok"), "summary": sec.get("summary"),
            "numbers": sec.get("numbers", {}),
        }
    return json.dumps(slim, ensure_ascii=False, indent=1)


def _parse_narrative(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return out
    if isinstance(payload.get("summary"), str) and payload["summary"].strip():
        out["__summary__"] = payload["summary"].strip()
    for item in payload.get("sections", []) or []:
        if isinstance(item, dict) and item.get("id"):
            out[str(item["id"])] = str(item.get("markdown", "")).strip()
    return out


# --------------------------------------------------------------------------- #
# Deterministic fallback narrative (no key / dry-run) — uses only engine summaries.
# --------------------------------------------------------------------------- #
def template_narrative(recipe: ReportRecipe, results: dict) -> Dict[str, str]:
    out: Dict[str, str] = {}
    sections = results.get("sections", {})
    bullets = []
    for sec in recipe.sections:
        r = sections.get(sec.id, {})
        summary = r.get("summary", "")
        if summary:
            out[sec.id] = summary
            bullets.append(f"- **{sec.heading}.** {summary}")
        elif r.get("error"):
            out[sec.id] = f"_This analysis could not be computed: {r['error']}_"
    if recipe.summary and bullets:
        ds = results.get("dataset", {})
        out["__summary__"] = (
            f"This report covers a dataset of {ds.get('rows', '?')} rows and "
            f"{ds.get('cols', '?')} columns. Key findings:\n\n" + "\n".join(bullets[:6]))
    return out
