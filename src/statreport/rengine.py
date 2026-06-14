"""
rengine.py — run the compute engine and render the final report.

Two responsibilities (the analog of EditMyRaw's apply-recipe + export):

  compute(): run the recipe with R/Quarto when present, else the Python engine.
             Returns the `results` dict (numbers + assets) — identical shape
             from either engine.

  render():  assemble narrative + figures + tables into a Quarto/markdown doc and
             render it to HTML/PDF/DOCX. The assembled .qmd/.md is ALSO saved next
             to the output — it *is* the reproducible recipe artifact (the big win
             this domain has over photo editing: re-run it and get the same report).

Degradation ladder (always produces *something*):
  compute:  R/Quarto  ->  Python (pandas/matplotlib/statsmodels)
  render:   quarto     ->  pandoc  ->  Python (markdown -> self-contained HTML)
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from . import pyengine, rcode
from .recipe import ReportRecipe

_EXT = {"html": ".html", "pdf": ".pdf", "docx": ".docx"}


def has_rscript() -> bool:
    return shutil.which("Rscript") is not None


def has_quarto() -> bool:
    return shutil.which("quarto") is not None


def has_pandoc() -> bool:
    return shutil.which("pandoc") is not None


# --------------------------------------------------------------------------- #
# compute
# --------------------------------------------------------------------------- #
def compute(recipe: ReportRecipe, data_path: str, df, assets_dir: str,
            engine: str = "auto", log: Optional[List[str]] = None) -> dict:
    log = log if log is not None else []
    os.makedirs(assets_dir, exist_ok=True)

    want_r = engine in ("auto", "r")
    if want_r and has_rscript():
        try:
            return _compute_r(recipe, data_path, assets_dir, log)
        except Exception as exc:
            log.append(f"R engine failed ({str(exc)[:120]}); using Python engine.")
    elif engine == "r":
        log.append("Rscript not found; using Python engine.")

    res = pyengine.compute(recipe, df, assets_dir)
    return res


def _compute_r(recipe: ReportRecipe, data_path: str, assets_dir: str, log: List[str]) -> dict:
    work = Path(assets_dir).parent
    script_path = work / "compute.R"
    results_path = work / "results.json"
    script_path.write_text(
        rcode.build_compute_r(recipe, os.path.abspath(data_path),
                              os.path.abspath(assets_dir), str(results_path)),
        encoding="utf-8")
    proc = subprocess.run(["Rscript", "--vanilla", str(script_path)],
                          capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not results_path.exists():
        raise RuntimeError((proc.stderr or proc.stdout or "Rscript error")[-300:])
    log.append("Computed with R engine.")
    return json.loads(results_path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# assemble
# --------------------------------------------------------------------------- #
def assemble_markdown(recipe: ReportRecipe, narrative: Dict[str, str],
                      results: dict) -> str:
    sections = results.get("sections", {})
    parts: List[str] = []

    if recipe.summary and narrative.get("__summary__"):
        parts.append("## Executive summary\n\n" + narrative["__summary__"].strip() + "\n")

    for sec in recipe.sections:
        r = sections.get(sec.id, {})
        parts.append(f"## {sec.heading}\n")
        text = (narrative.get(sec.id) or "").strip()
        if not text:
            text = r.get("summary", "") or ""
        if text:
            parts.append(text + "\n")
        if r.get("error"):
            parts.append(f"> *Analysis note: {r['error']}*\n")
        fig = r.get("figure")
        if fig:
            parts.append(f"![{sec.heading}]({fig})\n")
        tbl = r.get("table_markdown")
        if tbl and tbl not in ("NA", None):
            parts.append(str(tbl).strip() + "\n")
    return "\n".join(parts)


def _qmd_header(recipe: ReportRecipe, fmt: str) -> str:
    fmt_block = {
        "html": "  html:\n    toc: true\n    embed-resources: true",
        "pdf": "  pdf:\n    toc: true",
        "docx": "  docx:\n    toc: true",
    }.get(fmt, "  html:\n    embed-resources: true")
    sub = f'subtitle: "{recipe.subtitle}"\n' if recipe.subtitle else ""
    return (f'---\ntitle: "{recipe.title}"\n{sub}'
            f'lang: "{recipe.language}"\nformat:\n{fmt_block}\n'
            f'execute:\n  echo: false\n---\n\n')


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #
def render(recipe: ReportRecipe, narrative: Dict[str, str], results: dict,
           work_dir: str, stem: str, fmt: str = "html", engine: str = "auto",
           log: Optional[List[str]] = None) -> dict:
    log = log if log is not None else []
    fmt = fmt if fmt in _EXT else "html"
    os.makedirs(work_dir, exist_ok=True)
    body = assemble_markdown(recipe, narrative, results)

    # The reproducible artifact: always written, regardless of render success.
    qmd_path = os.path.join(work_dir, f"{stem}.qmd")
    Path(qmd_path).write_text(_qmd_header(recipe, fmt) + body, encoding="utf-8")
    md_path = os.path.join(work_dir, f"{stem}.md")
    Path(md_path).write_text(f"# {recipe.title}\n\n" + body, encoding="utf-8")

    out_path = os.path.join(work_dir, f"{stem}{_EXT[fmt]}")
    want_r = engine in ("auto", "r")

    # 1) Quarto
    if want_r and has_quarto():
        try:
            subprocess.run(["quarto", "render", qmd_path, "--to", fmt,
                            "--output", os.path.basename(out_path)],
                           capture_output=True, text=True, timeout=600, check=True,
                           cwd=work_dir)
            if os.path.exists(out_path):
                log.append(f"Rendered with Quarto -> {fmt}.")
                return _ok(out_path, qmd_path, results, "quarto")
        except Exception as exc:
            log.append(f"Quarto render failed ({str(exc)[:100]}); falling back.")

    # 2) pandoc
    if has_pandoc() and fmt in ("pdf", "docx", "html"):
        try:
            subprocess.run(["pandoc", md_path, "-o", out_path, "--standalone",
                            "--resource-path", work_dir],
                           capture_output=True, text=True, timeout=600, check=True,
                           cwd=work_dir)
            if os.path.exists(out_path):
                log.append(f"Rendered with pandoc -> {fmt}.")
                return _ok(out_path, qmd_path, results, "pandoc")
        except Exception as exc:
            log.append(f"pandoc render failed ({str(exc)[:100]}); falling back.")

    # 3) Python fallback -> self-contained HTML
    html = _markdown_to_html(recipe, body, work_dir)
    html_path = os.path.join(work_dir, f"{stem}.html")
    Path(html_path).write_text(html, encoding="utf-8")
    if fmt == "pdf":
        pdf = _html_to_pdf(html, os.path.join(work_dir, f"{stem}.pdf"))
        if pdf:
            log.append("Rendered PDF with WeasyPrint.")
            return _ok(pdf, qmd_path, results, "weasyprint")
        log.append("PDF needs Quarto, pandoc, or WeasyPrint — wrote self-contained HTML instead.")
    elif fmt == "docx":
        log.append("DOCX needs Quarto or pandoc — wrote self-contained HTML instead.")
    else:
        log.append("Rendered self-contained HTML (Python engine).")
    return _ok(html_path, qmd_path, results, "python-html")


def _ok(out_path, qmd_path, results, renderer) -> dict:
    return {"out_path": out_path, "artifact_path": qmd_path, "renderer": renderer}


# ---- python HTML rendering ---- #
_HTML_CSS = """
body{font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Helvetica,Arial,sans-serif;
  color:#1b1f2a;max-width:880px;margin:40px auto;padding:0 22px;background:#fff;}
h1{font-size:30px;letter-spacing:-.5px;margin-bottom:2px;}
h2{font-size:20px;margin-top:34px;border-bottom:2px solid #eef0f6;padding-bottom:6px;color:#2a2f3a;}
.subtitle{color:#6b7286;font-size:16px;margin-top:0;}
img{max-width:100%;height:auto;border:1px solid #e6e8f0;border-radius:8px;margin:14px 0;}
table{border-collapse:collapse;margin:14px 0;font-size:14px;width:100%;}
th,td{border:1px solid #e0e3ec;padding:6px 10px;text-align:right;}
th{background:#f6f7fb;text-align:left;}
td:first-child,th:first-child{text-align:left;}
blockquote{color:#8a5a2b;background:#fff7ec;border-left:3px solid #ff9d3c;margin:10px 0;padding:6px 14px;border-radius:0 6px 6px 0;}
footer{margin-top:50px;color:#9aa1b4;font-size:12px;border-top:1px solid #eef0f6;padding-top:12px;}
"""


def _markdown_to_html(recipe: ReportRecipe, body_md: str, base_dir: str) -> str:
    try:
        import markdown
        body_html = markdown.markdown(body_md, extensions=["tables", "fenced_code"])
    except Exception:
        body_html = "<pre>" + body_md.replace("<", "&lt;") + "</pre>"
    body_html = _inline_images(body_html, base_dir)
    sub = f'<p class="subtitle">{recipe.subtitle}</p>' if recipe.subtitle else ""
    return (f"<!doctype html><html lang='{recipe.language}'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{recipe.title}</title><style>{_HTML_CSS}</style></head><body>"
            f"<h1>{recipe.title}</h1>{sub}{body_html}"
            f"<footer>Generated by StatReport · engine: {recipe.mode.value} · "
            f"reproducible source saved alongside this file.</footer></body></html>")


def _inline_images(html: str, base_dir: str) -> str:
    def repl(m):
        src = m.group(1)
        path = os.path.join(base_dir, src)
        if os.path.exists(path):
            data = base64.b64encode(Path(path).read_bytes()).decode()
            return f'src="data:image/png;base64,{data}"'
        return m.group(0)
    return re.sub(r'src="([^"]+\.png)"', repl, html)


def _html_to_pdf(html: str, out_path: str) -> Optional[str]:
    try:
        from weasyprint import HTML
        HTML(string=html).write_pdf(out_path)
        return out_path
    except Exception:
        return None
