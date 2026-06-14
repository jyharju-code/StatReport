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

    args = parser.parse_args(argv)

    if args.cmd == "web":
        from .server import main as web_main
        web_main()
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


if __name__ == "__main__":
    main()
