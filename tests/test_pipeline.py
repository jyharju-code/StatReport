"""End-to-end (offline) pipeline test: dry-run produces a real report with grounded QA."""

import os

from statreport import pipeline


SAMPLE = os.path.join(os.path.dirname(__file__), "sample", "sales.csv")


def test_dry_run_end_to_end(tmp_path):
    res = pipeline.run([SAMPLE], out_dir=str(tmp_path), workflow="prompt",
                       mode="faithful", dry_run=True, engine="python", fmt="html")
    # an output file exists
    assert os.path.exists(res["out_path"])
    # the reproducible artifact exists
    assert os.path.exists(res["artifact_path"])
    # recipe + results + qa were saved
    for f in ("recipe.json", "results.json", "qa.json"):
        assert os.path.exists(os.path.join(str(tmp_path), f))
    # at least one section computed successfully
    oks = [s for s in res["results"]["sections"].values() if s["ok"]]
    assert oks
    # template narrative numbers come straight from results -> QA must be fully grounded
    assert res["qa"]["score"] == 100.0


def test_creative_dry_run_runs_regression(tmp_path):
    res = pipeline.run([SAMPLE], out_dir=str(tmp_path), workflow="prompt",
                       mode="creative", dry_run=True, engine="python", fmt="html")
    assert os.path.exists(res["out_path"])
    assert res["n_sections"] >= 1


def test_no_narrative(tmp_path):
    res = pipeline.run([SAMPLE], out_dir=str(tmp_path), dry_run=True, engine="python",
                       narrative=False, fmt="html")
    assert os.path.exists(res["out_path"])
    assert res["qa"]["checked"] == 0  # no prose -> nothing to verify
