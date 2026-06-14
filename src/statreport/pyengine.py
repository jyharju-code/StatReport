"""
pyengine.py — pure-Python compute engine (the always-available fallback).

This is one of the two deterministic executors (the other is rcode.py -> R/Quarto).
It is the statistics-domain analog of EditMyRaw's tone.py/geometry.py: the recipe
comes in, real numbers go out. The LLM is never in this path.

compute() returns a `results` dict:
  results["dataset"]            -> {rows, cols, columns}
  results["sections"][id]       -> {method, ok, error, figure, table_markdown,
                                     numbers, summary}
`numbers` holds the verifiable scalars; qa.py checks the narrative against them.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt  # noqa: E402

from .recipe import ReportRecipe, Section

REL = "assets"  # figures are referenced as assets/<id>.png from the report dir


def _num(x) -> Optional[float]:
    try:
        v = float(x)
        return round(v, 4) if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _numeric_cols(df: pd.DataFrame, prefer: List[str]) -> List[str]:
    nums = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    chosen = [c for c in prefer if c in nums] or nums
    return chosen


def _save_fig(fig, assets_dir: str, sid: str) -> str:
    os.makedirs(assets_dir, exist_ok=True)
    fname = f"{sid}.png"
    fig.savefig(os.path.join(assets_dir, fname), dpi=120, bbox_inches="tight")
    plt.close(fig)
    return f"{REL}/{fname}"


def _md(df: pd.DataFrame) -> str:
    try:
        return df.to_markdown()
    except Exception:
        return "```\n" + df.to_string() + "\n```"


# --------------------------------------------------------------------------- #
# per-method computations
# --------------------------------------------------------------------------- #
def _descriptive(df, a, sid, assets):
    nums = _numeric_cols(df, a.variables)
    out: dict = {"numbers": {"rows": len(df), "columns": df.shape[1]}}
    if nums:
        desc = df[nums].describe().T[["mean", "std", "min", "50%", "max"]].round(3)
        desc = desc.rename(columns={"50%": "median"})
        out["table_markdown"] = _md(desc)
        for c in nums:
            out["numbers"][f"{c}_mean"] = _num(df[c].mean())
            out["numbers"][f"{c}_median"] = _num(df[c].median())
    miss = int(df.isna().sum().sum())
    out["numbers"]["missing_cells"] = miss
    out["summary"] = (f"{len(df)} rows, {df.shape[1]} columns, "
                      f"{miss} missing cells.")
    return out


def _distribution(df, a, sid, assets):
    var = (a.variables or _numeric_cols(df, []))[:1]
    if not var:
        raise ValueError("no numeric variable for distribution")
    v = var[0]
    s = pd.to_numeric(df[v], errors="coerce").dropna()
    fig, ax = plt.subplots(figsize=(6, 3.6))
    ax.hist(s, bins=min(40, max(10, int(np.sqrt(len(s))))), color="#6f8cff", alpha=.85)
    ax.set_title(f"Distribution of {v}")
    ax.set_xlabel(v); ax.set_ylabel("count")
    figure = _save_fig(fig, assets, sid)
    numbers = {f"{v}_mean": _num(s.mean()), f"{v}_std": _num(s.std()),
               f"{v}_min": _num(s.min()), f"{v}_max": _num(s.max()),
               f"{v}_skew": _num(s.skew())}
    return {"figure": figure, "numbers": numbers,
            "summary": f"{v}: mean {numbers[f'{v}_mean']}, std {numbers[f'{v}_std']}."}


def _correlation(df, a, sid, assets):
    nums = _numeric_cols(df, a.variables)
    if len(nums) < 2:
        raise ValueError("need >=2 numeric variables for correlation")
    corr = df[nums].corr(numeric_only=True)
    fig, ax = plt.subplots(figsize=(5.5, 4.6))
    im = ax.imshow(corr.values, vmin=-1, vmax=1, cmap="coolwarm")
    ax.set_xticks(range(len(nums))); ax.set_xticklabels(nums, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(nums))); ax.set_yticklabels(nums, fontsize=8)
    fig.colorbar(im, ax=ax, fraction=.046, pad=.04)
    ax.set_title("Correlation matrix")
    figure = _save_fig(fig, assets, sid)
    # strongest off-diagonal pairs
    pairs = []
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            pairs.append((nums[i], nums[j], _num(corr.iloc[i, j])))
    pairs = [p for p in pairs if p[2] is not None]
    pairs.sort(key=lambda p: abs(p[2]), reverse=True)
    numbers = {f"corr_{a_}_{b_}": r for a_, b_, r in pairs[:6]}
    top = pairs[0] if pairs else None
    summary = (f"Strongest correlation: {top[0]} vs {top[1]} = {top[2]}." if top else "")
    return {"figure": figure, "table_markdown": _md(corr.round(2)),
            "numbers": numbers, "summary": summary}


def _comparison(df, a, sid, assets):
    if not a.variables or a.group_by is None:
        raise ValueError("comparison needs a variable and group_by")
    v, g = a.variables[0], a.group_by
    grp = df.groupby(g)[v].agg(["count", "mean", "median", "std"]).round(3)
    grp = grp.sort_values("mean", ascending=False).head(20)
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.bar([str(x) for x in grp.index], grp["mean"], color="#ff9d3c")
    ax.set_title(f"Mean {v} by {g}")
    ax.set_ylabel(f"mean {v}")
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8)
    figure = _save_fig(fig, assets, sid)
    numbers = {f"{v}_mean_{idx}": _num(row["mean"]) for idx, row in grp.iterrows()}
    hi, lo = grp.index[0], grp.index[-1]
    summary = (f"Highest mean {v}: {hi} ({grp.loc[hi,'mean']}); "
               f"lowest: {lo} ({grp.loc[lo,'mean']}).")
    return {"figure": figure, "table_markdown": _md(grp), "numbers": numbers,
            "summary": summary}


def _trend(df, a, sid, assets):
    v = (a.variables or _numeric_cols(df, []))[:1]
    if not v:
        raise ValueError("trend needs a numeric variable")
    v = v[0]
    t = a.time_var
    d = df[[c for c in [t, v] if c]].copy()
    if t:
        d[t] = pd.to_datetime(d[t], errors="coerce")
        d = d.dropna(subset=[t]).sort_values(t)
        x = d[t]
    else:
        x = np.arange(len(d))
    y = pd.to_numeric(d[v], errors="coerce")
    fig, ax = plt.subplots(figsize=(6.8, 3.6))
    ax.plot(x, y, color="#3fd6b0")
    ax.set_title(f"{v} over time"); ax.set_ylabel(v)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right", fontsize=8)
    figure = _save_fig(fig, assets, sid)
    first, last = _num(y.iloc[0]), _num(y.iloc[-1])
    change = _num(last - first) if (first is not None and last is not None) else None
    pct = _num((last - first) / first * 100) if first else None
    numbers = {f"{v}_first": first, f"{v}_last": last,
               f"{v}_change": change, f"{v}_pct_change": pct}
    return {"figure": figure, "numbers": numbers,
            "summary": f"{v} moved from {first} to {last} ({pct}% change)."}


def _crosstab(df, a, sid, assets):
    cols = [c for c in (a.variables + ([a.group_by] if a.group_by else [])) if c]
    cols = list(dict.fromkeys(cols))
    if len(cols) < 2:
        raise ValueError("crosstab needs two categorical variables")
    ct = pd.crosstab(df[cols[0]], df[cols[1]])
    fig, ax = plt.subplots(figsize=(5.6, 4.4))
    im = ax.imshow(ct.values, cmap="Blues")
    ax.set_xticks(range(ct.shape[1])); ax.set_xticklabels(ct.columns, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(ct.shape[0])); ax.set_yticklabels(ct.index, fontsize=8)
    fig.colorbar(im, ax=ax, fraction=.046, pad=.04)
    ax.set_title(f"{cols[0]} x {cols[1]}")
    figure = _save_fig(fig, assets, sid)
    return {"figure": figure, "table_markdown": _md(ct),
            "numbers": {"total": int(ct.values.sum())},
            "summary": f"Cross-tabulation of {cols[0]} and {cols[1]}."}


def _regression(df, a, sid, assets):
    try:
        import statsmodels.api as sm
    except Exception as exc:
        raise ValueError(f"statsmodels not available: {exc}")
    nums = _numeric_cols(df, a.variables)
    if len(nums) < 2:
        raise ValueError("regression needs a target + >=1 numeric predictor")
    y_name = nums[0]
    x_names = nums[1:] if len(a.variables) >= 2 else [c for c in nums if c != y_name]
    d = df[[y_name] + x_names].dropna()
    y = d[y_name].astype(float)
    X = sm.add_constant(d[x_names].astype(float))
    model = sm.OLS(y, X).fit()
    coef = pd.DataFrame({"coef": model.params.round(4),
                         "p_value": model.pvalues.round(4)})
    fig, ax = plt.subplots(figsize=(5.4, 4.0))
    ax.scatter(model.fittedvalues, y, s=12, color="#6f8cff", alpha=.6)
    lim = [min(y.min(), model.fittedvalues.min()), max(y.max(), model.fittedvalues.max())]
    ax.plot(lim, lim, color="#ff9d3c", lw=1)
    ax.set_xlabel("predicted"); ax.set_ylabel("actual"); ax.set_title(f"OLS: {y_name}")
    figure = _save_fig(fig, assets, sid)
    numbers = {"r_squared": _num(model.rsquared), "adj_r_squared": _num(model.rsquared_adj),
               "n_obs": int(model.nobs)}
    for name in model.params.index:
        numbers[f"coef_{name}"] = _num(model.params[name])
    return {"figure": figure, "table_markdown": _md(coef), "numbers": numbers,
            "summary": (f"OLS on {y_name}: R^2 = {numbers['r_squared']} "
                        f"(n = {numbers['n_obs']}).")}


def _forecast(df, a, sid, assets):
    v = (a.variables or _numeric_cols(df, []))[:1]
    if not v:
        raise ValueError("forecast needs a numeric variable")
    v = v[0]
    t = a.time_var
    d = df.copy()
    if t:
        d[t] = pd.to_datetime(d[t], errors="coerce")
        d = d.dropna(subset=[t]).sort_values(t)
    y = pd.to_numeric(d[v], errors="coerce").dropna().reset_index(drop=True)
    h = int(a.options.get("horizon", 6)) if isinstance(a.options, dict) else 6
    idx = np.arange(len(y))
    slope, intercept = np.polyfit(idx, y, 1)
    future = np.arange(len(y), len(y) + h)
    fc = intercept + slope * future
    fig, ax = plt.subplots(figsize=(6.8, 3.6))
    ax.plot(idx, y, color="#3fd6b0", label="actual")
    ax.plot(future, fc, color="#ff9d3c", ls="--", label="forecast")
    ax.set_title(f"{v}: linear-trend forecast (+{h})"); ax.legend(fontsize=8)
    figure = _save_fig(fig, assets, sid)
    numbers = {"trend_slope": _num(slope), "horizon": h,
               "forecast_last": _num(fc[-1]), "current_last": _num(y.iloc[-1])}
    return {"figure": figure, "numbers": numbers,
            "summary": (f"Linear-trend forecast for {v}: {numbers['current_last']} now "
                        f"-> {numbers['forecast_last']} in {h} periods.")}


_METHODS = {
    "descriptive": _descriptive, "distribution": _distribution,
    "correlation": _correlation, "comparison": _comparison, "trend": _trend,
    "crosstab": _crosstab, "regression": _regression, "timeseries_forecast": _forecast,
}


def compute(recipe: ReportRecipe, df: pd.DataFrame, assets_dir: str) -> dict:
    sections: Dict[str, dict] = {}
    for sec in recipe.sections:
        entry = {"method": sec.analysis.method, "heading": sec.heading,
                 "ok": False, "error": None, "figure": None,
                 "table_markdown": None, "numbers": {}, "summary": ""}
        fn = _METHODS.get(sec.analysis.method, _descriptive)
        try:
            res = fn(df, sec.analysis, sec.id, assets_dir)
            entry.update(res)
            entry["numbers"] = {k: v for k, v in entry.get("numbers", {}).items()
                                if v is not None}
            entry["ok"] = True
        except Exception as exc:  # one failure never kills the report
            entry["error"] = str(exc)[:300]
        sections[sec.id] = entry

    return {
        "engine": "python",
        "dataset": {"rows": len(df), "cols": df.shape[1],
                    "columns": [str(c) for c in df.columns]},
        "sections": sections,
    }
