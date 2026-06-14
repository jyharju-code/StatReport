"""
pipeline.py — orchestration for StatReport.

Workflows: 'prompt' | 'example' | 'combo'  (same trio as EditMyRaw).
Modes:     faithful | creative.

Per run: profile the data -> build a recipe (LLM or neutral) -> COMPUTE every number
with the R/Python engine -> write the narrative grounded in those numbers -> QA the
claims (and, with a key, run revision "sparring" rounds) -> render the report and
save the reproducible artifacts (recipe.json, results.json, the .qmd source).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import List, Optional

from . import data_io, qa as qa_mod, rengine
from .config import Settings, load_settings
from .profile import is_example, parse_example
from .recipe import Mode, neutral_recipe


def _noop(*_a, **_k):
    pass


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", str(text).strip().lower()).strip("-")
    return s or "report"


def run(data_inputs, out_dir="reports", *, workflow="prompt", mode="faithful",
        prompt="", example=None, fmt="html", engine="auto", dry_run=False,
        narrative=True, qa_rounds=2, qa_target=100.0,
        settings: Optional[Settings] = None, progress=None) -> dict:
    progress = progress or _noop
    settings = settings or load_settings()
    mode_enum = Mode(mode)
    log: List[str] = []

    # ---- data ----
    progress(0.04, "Loading data…")
    files = data_io.expand_inputs(data_inputs if isinstance(data_inputs, (list, tuple))
                                  else [data_inputs])
    if not files:
        raise ValueError("No supported data files found.")
    data_path = files[0]
    df, profile = data_io.load_and_profile(data_path)
    progress(0.12, f"Profiled {profile.rows} rows × {profile.cols} columns.")

    out_dir = os.path.abspath(os.path.expanduser(out_dir))
    os.makedirs(out_dir, exist_ok=True)
    assets_dir = os.path.join(out_dir, "assets")

    # ---- example report ----
    report_profile = None
    if example and str(example).lower() != "none" and os.path.exists(str(example)):
        if is_example(str(example)):
            progress(0.16, "Reading example report…")
            report_profile = parse_example(str(example))
            log.append(f"Example report: {len(report_profile.headings)} headings detected.")

    # ---- recipe ----
    client = None
    if not dry_run and settings.api_key:
        from .gemini import GeminiClient
        try:
            client = GeminiClient(settings)
        except Exception as exc:
            log.append(f"Gemini unavailable ({str(exc)[:120]}); running offline.")

    progress(0.22, "Planning report recipe…")
    if client is None:
        recipe = neutral_recipe(profile.column_names, mode_enum, prompt,
                                numeric=profile.numeric, categorical=profile.categorical,
                                datetime=profile.datetime)
        log.append("Recipe: neutral (no LLM)." if dry_run or not settings.api_key
                   else "Recipe: neutral (LLM unavailable).")
    else:
        recipe = client.build_recipe(profile, report_profile, prompt, mode_enum, workflow)
        log.append(f"Recipe: {len(recipe.sections)} sections planned by {settings.model}.")

    # ---- compute (numbers live here, never in the model) ----
    progress(0.40, "Computing analyses…")
    results = rengine.compute(recipe, data_path, df, assets_dir, engine=engine, log=log)

    # ---- narrative ----
    from .gemini import template_narrative
    narr: dict = {}
    if narrative:
        progress(0.62, "Writing narrative…")
        if client is None:
            narr = template_narrative(recipe, results)
        else:
            try:
                narr = client.write_narrative(recipe, results, report_profile, mode_enum)
            except Exception as exc:
                log.append(f"Narrative LLM failed ({str(exc)[:120]}); used template prose.")
                narr = template_narrative(recipe, results)

    # ---- QA claim-check + sparring rounds ----
    progress(0.74, "QA: checking every number against the data…")
    qa = qa_mod.check_claims(narr, results)
    log.append(qa_mod.format_log(qa))
    if client is not None and narr and qa["issues"] and qa_rounds > 0:
        for r in range(qa_rounds):
            if qa["score"] >= qa_target:
                break
            progress(0.74 + 0.06 * (r + 1) / qa_rounds,
                     f"QA sparring round {r + 1}/{qa_rounds}…")
            try:
                narr = client.revise_narrative(recipe, results, narr, qa["issues"], r)
            except Exception as exc:
                log.append(f"Revision round {r + 1} skipped ({str(exc)[:80]}).")
                break
            qa = qa_mod.check_claims(narr, results)
            log.append(f"round {r + 1}: " + qa_mod.format_log(qa))

    # ---- render ----
    progress(0.88, "Rendering report…")
    stem = _slug(recipe.title) or _slug(profile.name)
    render = rengine.render(recipe, narr, results, work_dir=out_dir, stem=stem,
                            fmt=fmt, engine=engine, log=log)

    # ---- save reproducible artifacts ----
    Path(os.path.join(out_dir, "recipe.json")).write_text(
        json.dumps(recipe.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
    Path(os.path.join(out_dir, "results.json")).write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    Path(os.path.join(out_dir, "qa.json")).write_text(
        json.dumps(qa, indent=2, ensure_ascii=False), encoding="utf-8")

    progress(1.0, f"Done — {render['out_path']}")
    return {
        "out_path": render["out_path"], "artifact_path": render["artifact_path"],
        "renderer": render["renderer"], "out_dir": out_dir,
        "recipe": recipe.model_dump(mode="json"), "results": results, "qa": qa,
        "log": log, "key_source": settings.key_source,
        "n_sections": len(recipe.sections), "engine": results.get("engine", "python"),
    }
