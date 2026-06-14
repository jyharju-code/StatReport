"""cli.py — command line for StatReport (report / key / web)."""

from __future__ import annotations

import sys

from . import config, data_io, pipeline


def main(argv=None) -> None:
    import argparse
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

    sub.add_parser("web", help="Launch the browser GUI.")
    sub.add_parser("setup-r", help="Install the R packages the rich engine uses.")

    args = parser.parse_args(argv)

    if args.cmd == "web":
        from .server import main as web_main
        web_main()
        return

    if args.cmd == "setup-r":
        setup_r()
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
