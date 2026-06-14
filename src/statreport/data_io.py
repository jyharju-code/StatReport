"""
data_io.py — load tabular data and build a compact DATA PROFILE.

Analog of EditMyRaw's raw_io.py + the look-profile computation in style.py:
the heavy raw thing (the dataset) is read locally; only a small, structured
*profile* (schema, types, missingness, summaries, a tiny sample) is ever shown
to the model — exactly like only a downscaled preview goes to Gemini in EditMyRaw.
"""

from __future__ import annotations

import glob
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

SUPPORTED_EXT = {".csv", ".tsv", ".txt", ".xlsx", ".xls", ".parquet", ".json",
                 ".sqlite", ".db", ".sqlite3"}


def is_supported(path: str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXT


def expand_inputs(items) -> List[str]:
    """Mirror of EditMyRaw.pipeline.expand_inputs — files / folders / globs."""
    files: List[str] = []
    for item in items or []:
        item = os.path.expanduser(str(item))
        if os.path.isdir(item):
            for name in sorted(os.listdir(item)):
                p = os.path.join(item, name)
                if os.path.isfile(p) and is_supported(p):
                    files.append(p)
        elif any(ch in item for ch in "*?["):
            files.extend(sorted(p for p in glob.glob(item) if is_supported(p)))
        elif os.path.isfile(item) and is_supported(item):
            files.append(item)
    seen, out = set(), []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def load_table(path: str) -> pd.DataFrame:
    """Load the primary table from a data file."""
    path = os.path.expanduser(path)
    ext = Path(path).suffix.lower()
    if ext == ".csv":
        return pd.read_csv(path)
    if ext in {".tsv", ".txt"}:
        return pd.read_csv(path, sep="\t")
    if ext in {".xlsx", ".xls"}:
        return pd.read_excel(path)            # first sheet
    if ext == ".parquet":
        return pd.read_parquet(path)
    if ext == ".json":
        return pd.read_json(path)
    if ext in {".sqlite", ".db", ".sqlite3"}:
        con = sqlite3.connect(path)
        try:
            names = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", con)
            if names.empty:
                raise ValueError("SQLite file has no tables.")
            first = names["name"].iloc[0]
            return pd.read_sql(f"SELECT * FROM '{first}'", con)
        finally:
            con.close()
    raise ValueError(f"Unsupported data file: {path}")


@dataclass
class ColumnProfile:
    name: str
    kind: str          # numeric | categorical | datetime | boolean | text
    n: int
    missing: int
    n_unique: int
    stats: dict = field(default_factory=dict)   # numeric/datetime summary
    top: dict = field(default_factory=dict)      # categorical top values -> count
    samples: list = field(default_factory=list)


@dataclass
class DataProfile:
    name: str
    rows: int
    cols: int
    columns: List[ColumnProfile]

    @property
    def column_names(self) -> List[str]:
        return [c.name for c in self.columns]

    def _names(self, kind: str) -> List[str]:
        return [c.name for c in self.columns if c.kind == kind]

    @property
    def numeric(self) -> List[str]:
        return self._names("numeric")

    @property
    def categorical(self) -> List[str]:
        return self._names("categorical") + self._names("boolean")

    @property
    def datetime(self) -> List[str]:
        return self._names("datetime")

    def to_dict(self) -> dict:
        return {
            "name": self.name, "rows": self.rows, "cols": self.cols,
            "columns": [{
                "name": c.name, "kind": c.kind, "missing": c.missing,
                "n_unique": c.n_unique, "stats": c.stats, "top": c.top,
                "samples": c.samples,
            } for c in self.columns],
        }

    def data_dictionary_text(self) -> str:
        """A compact, model-readable schema description."""
        lines = [f"Dataset '{self.name}': {self.rows} rows x {self.cols} columns.", ""]
        for c in self.columns:
            bits = [f"- {c.name} [{c.kind}]"]
            if c.missing:
                bits.append(f"{c.missing} missing")
            bits.append(f"{c.n_unique} unique")
            if c.kind == "numeric" and c.stats:
                bits.append("range {min}..{max}, mean {mean}".format(**c.stats))
            elif c.kind in {"categorical", "boolean"} and c.top:
                tops = ", ".join(f"{k} ({v})" for k, v in list(c.top.items())[:5])
                bits.append("top: " + tops)
            elif c.kind == "datetime" and c.stats:
                bits.append("from {min} to {max}".format(**c.stats))
            lines.append("  ".join(bits))
        return "\n".join(lines)


def _round(x) -> Optional[float]:
    try:
        v = float(x)
        if not np.isfinite(v):
            return None
        return round(v, 4)
    except (TypeError, ValueError):
        return None


def _classify(series: pd.Series) -> str:
    s = series.dropna()
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    # object / string: try to parse as datetime, else categorical vs free text
    if len(s) > 0:
        sample = s.astype(str).head(50)
        try:
            parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
        except (TypeError, ValueError):
            parsed = pd.to_datetime(sample, errors="coerce")
        if parsed.notna().mean() >= 0.8:
            return "datetime"
    n_unique = s.nunique()
    if len(s) and (n_unique <= 50 or n_unique / max(1, len(s)) < 0.5):
        return "categorical"
    return "text"


def profile_dataframe(df: pd.DataFrame, name: str = "dataset") -> DataProfile:
    columns: List[ColumnProfile] = []
    n = len(df)
    for col in df.columns:
        series = df[col]
        kind = _classify(series)
        missing = int(series.isna().sum())
        valid = series.dropna()
        n_unique = int(valid.nunique())
        stats: dict = {}
        top: dict = {}
        samples: list = []

        if kind == "numeric":
            num = pd.to_numeric(valid, errors="coerce").dropna()
            if len(num):
                stats = {
                    "min": _round(num.min()), "max": _round(num.max()),
                    "mean": _round(num.mean()), "median": _round(num.median()),
                    "std": _round(num.std()),
                }
        elif kind == "datetime":
            dt = pd.to_datetime(valid, errors="coerce").dropna()
            if len(dt):
                stats = {"min": str(dt.min().date()), "max": str(dt.max().date())}
        elif kind in {"categorical", "boolean"}:
            vc = valid.astype(str).value_counts().head(10)
            top = {str(k): int(v) for k, v in vc.items()}
        else:  # text
            samples = [str(x) for x in valid.astype(str).head(3).tolist()]

        if not samples:
            samples = [str(x) for x in valid.head(3).tolist()]

        columns.append(ColumnProfile(
            name=str(col), kind=kind, n=n, missing=missing,
            n_unique=n_unique, stats=stats, top=top, samples=samples))

    return DataProfile(name=name, rows=n, cols=len(df.columns), columns=columns)


def load_and_profile(path: str) -> tuple:
    """Convenience: return (DataFrame, DataProfile)."""
    df = load_table(path)
    profile = profile_dataframe(df, name=Path(path).stem)
    return df, profile
