"""
extract.py — pull TABLES of numbers out of a PDF into tabular data (CSV / DataFrame).

A deliberately SEPARATE pipeline from the report flow: here the PDF is a *data source*,
not a style example. It still honours StatReport's rule that numbers must be trustworthy:

  * Deterministic first — pdfplumber reads the actual cell text from the PDF. Exact
    numbers, no model involved. Works on ruled/typeset data tables (the common case).
  * Gemini second (only for hard PDFs, e.g. borderless/typeset/scanned, and only with a
    key) — multimodal table extraction. NEVER trusted blindly: every extracted number is
    GROUNDED against the PDF's own raw text, and ungrounded cells are flagged. A model
    that invents a figure is caught, exactly like the report QA pass.

Engines: "auto" (pdfplumber, then Gemini if nothing found and a key exists),
"pdfplumber" (deterministic only), "gemini" (force multimodal).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pandas as pd


@dataclass
class ExtractedTable:
    page: int
    source: str               # "pdfplumber" | "gemini"
    columns: List[str]
    rows: List[List[str]]
    grounding: float = 1.0    # fraction of numeric cells whose digits appear in the PDF text
    title: str = ""
    ungrounded: List[str] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return len(self.columns)

    def to_dataframe(self) -> pd.DataFrame:
        ncol = max([len(self.columns)] + [len(r) for r in self.rows] or [0])
        cols = [(self.columns[i] if i < len(self.columns) and self.columns[i] else f"col{i+1}")
                for i in range(ncol)]
        norm = [(r + [""] * (ncol - len(r)))[:ncol] for r in self.rows]
        df = pd.DataFrame(norm, columns=cols)
        # turn clean numeric columns into real numbers (so the report engine can use them)
        for c in df.columns:
            conv = pd.to_numeric(df[c].map(_num_token), errors="coerce")
            if conv.notna().mean() >= 0.8:
                df[c] = conv
        return df


_NUM = re.compile(r"-?\d[\d.,]*\d|\d")


def _num_token(cell) -> str:
    """Best numeric reading of a cell ('€1,982,431' -> '1982431', '23.4%' -> '23.4')."""
    s = str(cell).strip()
    m = re.search(r"-?\d[\d, ]*\.?\d*", s)
    if not m:
        return ""
    t = m.group(0).replace(" ", "").replace(",", "")
    return t


def _digits(s: str) -> str:
    return re.sub(r"\D", "", str(s))


def extract_text(pdf_path: str) -> str:
    import pdfplumber
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _ground(columns: List[str], rows: List[List[str]], digits_text: str) -> tuple:
    """Fraction of numeric tokens (>=2 digits) found in the PDF's own text."""
    total, found, missing = 0, 0, []
    for row in rows:
        for cell in row:
            for tok in _NUM.findall(str(cell)):
                d = _digits(tok)
                if len(d) < 2:
                    continue
                total += 1
                if d in digits_text:
                    found += 1
                else:
                    missing.append(tok)
    return (found / total if total else 1.0), missing[:20]


def _parse_pages(spec: Optional[str]) -> Optional[set]:
    if not spec:
        return None
    out: set = set()
    for part in str(spec).split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        elif part:
            out.add(int(part))
    return out or None


def _pdfplumber_tables(pdf_path: str, pages: Optional[set]) -> List[ExtractedTable]:
    import pdfplumber
    tables: List[ExtractedTable] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            if pages and i not in pages:
                continue
            for raw in page.extract_tables() or []:
                grid = [["" if c is None else str(c).strip() for c in row] for row in raw if any(row)]
                if len(grid) < 2:
                    continue
                tables.append(ExtractedTable(page=i, source="pdfplumber",
                                             columns=grid[0], rows=grid[1:]))
    return tables


def _gemini_tables(pdf_path: str, client, pages: Optional[set]) -> List[ExtractedTable]:
    out: List[ExtractedTable] = []
    for t in client.extract_tables(pdf_path):
        page = int(t.get("page", 0) or 0)
        if pages and page and page not in pages:
            continue
        cols = [str(c) for c in (t.get("columns") or [])]
        rows = [[str(c) for c in r] for r in (t.get("rows") or [])]
        if not rows:
            continue
        out.append(ExtractedTable(page=page, source="gemini", columns=cols, rows=rows,
                                  title=str(t.get("title", ""))))
    return out


def extract_pdf(pdf_path: str, engine: str = "auto", pages: Optional[str] = None,
                client=None) -> List[ExtractedTable]:
    pdf_path = os.path.expanduser(pdf_path)
    page_set = _parse_pages(pages)

    tables: List[ExtractedTable] = []
    if engine in ("auto", "pdfplumber"):
        tables = _pdfplumber_tables(pdf_path, page_set)

    if not tables and engine in ("auto", "gemini") and client is not None:
        tables = _gemini_tables(pdf_path, client, page_set)
    elif engine == "gemini" and client is not None:
        tables = _gemini_tables(pdf_path, client, page_set)

    # ground every table against the PDF's own text (so AI-extracted numbers are checked)
    digits_text = _digits(extract_text(pdf_path))
    for t in tables:
        t.grounding, t.ungrounded = _ground(t.columns, t.rows, digits_text)
    return tables


def to_csv(tables: List[ExtractedTable], out_dir: str, stem: str = "table") -> List[str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for idx, t in enumerate(tables, start=1):
        path = os.path.join(out_dir, f"{stem}_p{t.page}_t{idx}.csv")
        t.to_dataframe().to_csv(path, index=False)
        paths.append(path)
    return paths
