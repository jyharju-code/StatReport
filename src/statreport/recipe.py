"""
recipe.py — the report recipe (sections + analyses + tone).

This is the statistics-domain analog of EditMyRaw's recipe.py. The model is
LENIENT: it accepts whatever the LLM returns. All safety happens in
`bounded()`, which is the analog of EditMyRaw's `bounded_for_mode()`:

  * In EditMyRaw every numeric value is clamped to a safe range per mode.
  * Here every analysis is clamped to *reality*: variables must be real
    columns, methods must be on the per-mode allowlist, charts/tables must be
    known kinds, and the number of sections is capped.

A recipe can therefore only ask for analyses that the engine can actually run
on the actual data — it can never reference a column that does not exist.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class Mode(str, Enum):
    faithful = "faithful"   # conservative methods only; prose strictly from computed numbers
    creative = "creative"   # adds modelling/forecasting + richer interpretation


# Methods the engine knows how to run. Faithful = descriptive/relational only.
FAITHFUL_METHODS = {"descriptive", "comparison", "correlation", "trend",
                    "distribution", "crosstab"}
CREATIVE_EXTRA = {"regression", "timeseries_forecast"}
ALL_METHODS = FAITHFUL_METHODS | CREATIVE_EXTRA

CHART_KINDS = {"none", "bar", "line", "scatter", "hist", "box", "heatmap"}
TABLE_KINDS = {"none", "summary", "model", "crosstab", "head"}
TONES = {"neutral", "executive", "academic", "technical", "plain"}

MAX_SECTIONS = 12


def _clean_str(value, default: str = "") -> str:
    try:
        return str(value).strip()
    except Exception:
        return default


class AnalysisSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    method: str = "descriptive"
    variables: List[str] = Field(default_factory=list)
    group_by: Optional[str] = None
    time_var: Optional[str] = None
    chart: str = "none"
    table: str = "summary"
    options: Dict[str, object] = Field(default_factory=dict)


class Section(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = ""
    heading: str = ""
    narrative: bool = True
    description: str = ""  # guidance for the narrative writer (NOT shown verbatim)
    analysis: AnalysisSpec = Field(default_factory=AnalysisSpec)


class ReportRecipe(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mode: Mode = Mode.faithful
    title: str = "Data Report"
    subtitle: str = ""
    audience: str = "general"
    tone: str = "neutral"
    language: str = "en"
    summary: bool = True            # include an executive-summary section up top
    diagnosis: str = ""             # the model's read of the data / plan (free text)
    sections: List[Section] = Field(default_factory=list)

    # ------------------------------------------------------------------ #
    # The safety layer — analog of EditMyRaw.recipe.bounded_for_mode()
    # ------------------------------------------------------------------ #
    def bounded(self, columns: List[str], mode: Mode) -> "ReportRecipe":
        """Pin everything to reality: real columns, allowed methods, known kinds."""
        cols = list(columns)
        colset = set(cols)
        allowed = FAITHFUL_METHODS if mode == Mode.faithful else ALL_METHODS

        data = self.model_dump()
        data["mode"] = mode.value
        recipe = ReportRecipe.model_validate(data)

        recipe.tone = recipe.tone if recipe.tone in TONES else "neutral"
        recipe.title = _clean_str(recipe.title) or "Data Report"
        recipe.language = (_clean_str(recipe.language) or "en")[:8]

        clean_sections: List[Section] = []
        for i, sec in enumerate(recipe.sections[:MAX_SECTIONS]):
            a = sec.analysis
            a.method = a.method if a.method in allowed else "descriptive"
            # variables / group_by / time_var must be real columns
            a.variables = [v for v in a.variables if v in colset]
            a.group_by = a.group_by if a.group_by in colset else None
            a.time_var = a.time_var if a.time_var in colset else None
            a.chart = a.chart if a.chart in CHART_KINDS else "none"
            a.table = a.table if a.table in TABLE_KINDS else "summary"

            # Methods that NEED specific inputs degrade gracefully if they're missing.
            if a.method == "comparison" and (not a.variables or a.group_by is None):
                a.method = "descriptive"
            if a.method == "crosstab" and len(a.variables) < 2 and a.group_by is None:
                a.method = "descriptive"
            if a.method == "correlation" and len(a.variables) < 2:
                # fall back to all numerics later; keep as correlation, engine handles it
                pass
            if a.method == "trend" and a.time_var is None and not a.variables:
                a.method = "descriptive"
            if a.method == "regression" and len(a.variables) < 2:
                a.method = "descriptive"
            if a.method == "timeseries_forecast" and a.time_var is None and not a.variables:
                a.method = "descriptive"

            sec.id = _clean_str(sec.id) or f"sec{i + 1}"
            sec.heading = _clean_str(sec.heading) or f"Section {i + 1}"
            clean_sections.append(sec)

        # de-duplicate section ids
        seen: set = set()
        for j, sec in enumerate(clean_sections):
            if sec.id in seen:
                sec.id = f"{sec.id}_{j + 1}"
            seen.add(sec.id)

        recipe.sections = clean_sections or neutral_recipe(cols, mode).sections
        return recipe


# --------------------------------------------------------------------------- #
# neutral_recipe — the no-LLM default (analog of EditMyRaw.neutral_recipe).
# Produces a genuinely useful multi-section report straight from the columns,
# so --dry-run and "no key" still output a real report.
# --------------------------------------------------------------------------- #
def neutral_recipe(columns: List[str], mode: Mode = Mode.faithful, prompt: str = "",
                   *, numeric: Optional[List[str]] = None,
                   categorical: Optional[List[str]] = None,
                   datetime: Optional[List[str]] = None) -> ReportRecipe:
    numeric = numeric or []
    categorical = categorical or []
    datetime = datetime or []

    sections: List[Section] = []

    sections.append(Section(
        id="overview", heading="Data overview", narrative=True,
        description="Describe the dataset size, the variables, and data quality (missingness).",
        analysis=AnalysisSpec(method="descriptive", variables=numeric, table="summary"),
    ))

    if len(numeric) >= 2:
        sections.append(Section(
            id="correlations", heading="Relationships between numeric variables",
            description="Report the strongest correlations and what they suggest.",
            analysis=AnalysisSpec(method="correlation", variables=numeric,
                                  chart="heatmap", table="none"),
        ))

    if numeric and categorical:
        sections.append(Section(
            id="bygroup", heading=f"{numeric[0]} by {categorical[0]}",
            description="Compare the numeric measure across groups.",
            analysis=AnalysisSpec(method="comparison", variables=[numeric[0]],
                                  group_by=categorical[0], chart="bar", table="summary"),
        ))

    if datetime and numeric:
        sections.append(Section(
            id="trend", heading=f"{numeric[0]} over time",
            description="Describe the trend over time and the net change.",
            analysis=AnalysisSpec(method="trend", variables=[numeric[0]],
                                  time_var=datetime[0], chart="line", table="none"),
        ))

    for v in numeric[:3]:
        sections.append(Section(
            id=f"dist_{v}", heading=f"Distribution of {v}",
            description="Summarise the distribution (centre, spread, skew, outliers).",
            analysis=AnalysisSpec(method="distribution", variables=[v],
                                  chart="hist", table="none"),
        ))

    diagnosis = "Neutral recipe (no LLM call)."
    if prompt:
        diagnosis += f" Prompt noted: {prompt[:200]}"

    return ReportRecipe(
        mode=mode, title="Data Report", diagnosis=diagnosis, sections=sections,
    ).bounded(columns, mode)
