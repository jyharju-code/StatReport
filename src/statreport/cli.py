"""cli.py — command line for StatReport (report / key / web)."""

from __future__ import annotations

import sys

from . import config, data_io, pipeline


def main(argv=None) -> None:
    import argparse
    import warnings
    # Silence noisy third-party notices (we intentionally support Python 3.9).
    for _msg in (r".*past its end of life.*", r".*OpenSSL 1\.1\.1.*", r".*LibreSSL.*"):
        warnings.filterwarnings("ignore", message=_msg)
    parser = argparse.ArgumentParser(
        prog="statreport",
        description="Example report + your data -> a statistical report (R/Quarto via a Gemini recipe).")
    sub = parser.add_subparsers(dest="cmd")

    r = sub.add_parser("report", help="Build a report (default).")
    r.add_argument("--data", nargs="+", required=True, help="Data file(s) / folder / glob (CSV, XLSX, Parquet, …).")
    r.add_argument("--out", default="reports", help="Output folder.")
    r.add_argument("--example", help="Example report to imitate (PDF/DOCX/MD/HTML).")
    r.add_argument("--workflow", choices=["prompt", "example", "combo"], default="prompt")
    r.add_argument("--mode", choices=["faithful", "creative"], default="faithful")
    r.add_argument("--prompt", default="")
    r.add_argument("--format", dest="fmt", choices=["html", "pdf", "docx"], default="html")
    r.add_argument("--engine", choices=["auto", "r", "python"], default="auto")
    r.add_argument("--no-narrative", action="store_true", help="Tables/figures only, no prose.")
    r.add_argument("--qa-rounds", type=int, default=2, help="Narrative revision rounds (needs a key).")
    r.add_argument("--dry-run", action="store_true", help="No LLM — neutral recipe + template prose.")

    k = sub.add_parser("key", help="Manage the local API key.")
    k.add_argument("--set", dest="set_key")
    k.add_argument("--show", action="store_true")
    k.add_argument("--clear", action="store_true")

    w = sub.add_parser("web", help="Launch the desktop app (native window).")
    w.add_argument("--browser", action="store_true",
                   help="Open in the default browser instead of a native window.")
    sub.add_parser("setup-r", help="Install the R packages the rich engine uses.")

    ex = sub.add_parser("extract", help="Extract tables of numbers from a PDF into CSV.")
    ex.add_argument("--pdf", required=True, help="PDF to extract tables from.")
    ex.add_argument("--out", default="extracted", help="Output folder for the CSV(s).")
    ex.add_argument("--engine", choices=["auto", "pdfplumber", "gemini"], default="auto",
                    help="auto: pdfplumber, then Gemini if nothing found and a key is set.")
    ex.add_argument("--pages", help="Limit to pages, e.g. '1-3' or '2'.")

    args = parser.parse_args(argv)

    if args.cmd == "web":
        from .server import main as web_main
        web_main(browser=args.browser)
        return

    if args.cmd == "setup-r":
        setup_r()
        return

    if args.cmd == "extract":
        run_extract(args)
        return

    if args.cmd == "key":
        if args.set_key:
            config.save_api_key(args.set_key)
            print("Key saved to", config.CONFIG_FILE)
        elif args.clear:
            config.clear_api_key()
            print("Key cleared.")
        status = config.key_status()
        print(f"Key: {status['masked'] or 'not set'} (source: {status['source']})")
        return

    if args.cmd in (None, "report"):
        if args.cmd is None:
            parser.print_help()
            return
        files = data_io.expand_inputs(args.data)
        if not files:
            sys.exit("No supported data files found.")
        print(f"data: {files[0]} | workflow={args.workflow} mode={args.mode} "
              f"format={args.fmt} engine={args.engine}")

        def progress(fr, m):
            sys.stdout.write(f"\r[{int(fr*100):3d}%] {m:<60}")
            sys.stdout.flush()

        res = pipeline.run(
            files, out_dir=args.out, workflow=args.workflow, mode=args.mode,
            prompt=args.prompt, example=args.example, fmt=args.fmt, engine=args.engine,
            narrative=not args.no_narrative, qa_rounds=args.qa_rounds, dry_run=args.dry_run,
            progress=progress)
        print()
        for line in res["log"]:
            print("  •", line)
        print(f"Report: {res['out_path']}")
        print(f"Source: {res['artifact_path']}  (re-render anytime)")
        print(f"QA: {res['qa']['score']}/100 grounded "
              f"({res['qa']['verified']}/{res['qa']['checked']} numeric claims).")


def run_extract(args) -> None:
    """PDF -> data: pull tables of numbers out of a PDF into CSV(s)."""
    from pathlib import Path

    from . import config, extract

    settings = config.load_settings()

    # Deterministic first — no model, no Google import in the common (ruled-PDF) case.
    tables = []
    if args.engine in ("auto", "pdfplumber"):
        tables = extract.extract_pdf(args.pdf, engine="pdfplumber", pages=args.pages)

    # Gemini only if nothing was found (auto) or explicitly requested.
    if (not tables and args.engine == "auto") or args.engine == "gemini":
        if settings.api_key:
            try:
                from .gemini import GeminiClient
                client = GeminiClient(settings)
                tables = extract.extract_pdf(args.pdf, engine="gemini", pages=args.pages, client=client)
            except Exception as exc:
                print("Gemini unavailable:", str(exc)[:140])
        elif args.engine == "gemini":
            print("--engine gemini needs a Gemini API key (set one in the GUI or `statreport key --set`).")
            return

    if not tables:
        if args.engine == "gemini" or settings.api_key:
            print("No tables extracted from this PDF.")
        else:
            print("No ruled tables found (this PDF may be borderless/typeset/scanned).")
            print("With a Gemini key set, '--engine gemini' can read it multimodally.")
        return

    paths = extract.to_csv(tables, args.out, stem=Path(args.pdf).stem)
    print(f"Extracted {len(tables)} table(s) from {args.pdf}:")
    for t, p in zip(tables, paths):
        flag = "" if t.grounding >= 0.999 else \
            f"  ⚠ grounding {t.grounding * 100:.0f}% — unverified: {', '.join(t.ungrounded[:5])}"
        print(f"  page {t.page} [{t.source}] {t.n_rows}×{t.n_cols} -> {p}{flag}")
    if any(t.grounding < 0.999 for t in tables):
        print("Note: flagged numbers were NOT found in the PDF's own text — verify before use.")
    print(f"\nAnalyse one:  statreport report --data {paths[0]} --dry-run --out report")


def setup_r() -> None:
    """Set up the rich R engine: check R/Quarto/pandoc, install the R packages."""
    import shutil
    import subprocess

    rscript = shutil.which("Rscript")
    if rscript is None:
        print("R is not installed. Install it first:")
        if sys.platform == "darwin":
            print("  brew install r            # or download from https://cloud.r-project.org")
        elif sys.platform.startswith("win"):
            print("  winget install RProject.R  # or https://cloud.r-project.org")
        else:
            print("  use your package manager, or https://cloud.r-project.org")
        print("Optional for PDF/DOCX: install Quarto (https://quarto.org) or pandoc.")
        return

    print(f"Found R: {rscript}")
    for tool in ("quarto", "pandoc"):
        found = shutil.which(tool)
        print(f"  {tool}: {found or 'not found (HTML still works; needed for polished PDF/DOCX)'}")

    from .rcode import bootstrap_r_code
    print("Installing/verifying StatReport R packages (this can take a while on first run)…")
    subprocess.run([rscript, "-e", bootstrap_r_code()])


if __name__ == "__main__":
    main()
