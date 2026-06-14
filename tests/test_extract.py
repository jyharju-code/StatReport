"""Tests for the PDF -> data extraction pipeline (deterministic path; no key needed)."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from statreport import extract  # noqa: E402


def _make_ruled_pdf(path):
    cols = ["Region", "Revenue", "Margin %"]
    data = [["North", "1,982,431", "23.4"],
            ["South", "1,403,118", "19.1"],
            ["East", "1,712,560", "21.8"]]
    fig, ax = plt.subplots(figsize=(7, 2.2))
    ax.axis("off")
    tbl = ax.table(cellText=data, colLabels=cols, loc="center", cellLoc="center")
    tbl.scale(1, 1.5)
    fig.savefig(str(path))
    plt.close(fig)


def test_pdfplumber_extracts_exact_numbers(tmp_path):
    pdf = tmp_path / "t.pdf"
    _make_ruled_pdf(pdf)
    tables = extract.extract_pdf(str(pdf), engine="pdfplumber")
    assert tables, "no table extracted from a ruled PDF"
    t = tables[0]
    assert "Region" in t.columns
    df = t.to_dataframe()
    assert (df["Region"] == "North").any()
    # the comma-formatted revenue is parsed to a real number, exactly
    assert 1982431 in set(int(x) for x in df["Revenue"].tolist())
    # deterministic extraction is fully grounded by construction
    assert t.grounding == 1.0


def test_grounding_flags_fabricated_numbers(tmp_path):
    pdf = tmp_path / "t.pdf"
    _make_ruled_pdf(pdf)
    digits = extract._digits(extract.extract_text(str(pdf)))
    # 1,982,431 is really in the PDF; 9,876,543 is not
    g_real, _ = extract._ground(["x"], [["1,982,431"]], digits)
    g_fake, missing = extract._ground(["x"], [["9,876,543"]], digits)
    assert g_real == 1.0
    assert g_fake == 0.0 and "9,876,543" in missing


def test_num_token_normalisation():
    assert extract._num_token("€1,982,431") == "1982431"
    assert extract._num_token("23.4%") == "23.4"
    assert extract._num_token("n/a") == ""
