"""R engine tests — skipped automatically when Rscript is not installed.

These lock in the rich R path as a *tested* part of the distribution: every method
must compute via R (jsonlite + ggplot2 + the report tooling) and return the same
results shape the Python engine does.
"""

import os
import shutil

import pandas as pd
import pytest

from statreport import rengine
from statreport.recipe import AnalysisSpec, Mode, ReportRecipe, Section, neutral_recipe

pytestmark = pytest.mark.skipif(shutil.which("Rscript") is None,
                                reason="Rscript not installed")

SAMPLE = os.path.join(os.path.dirname(__file__), "sample", "sales.csv")


def _df():
    return pd.read_csv(SAMPLE)


def test_r_engine_neutral_recipe(tmp_path):
    df = _df()
    recipe = neutral_recipe(list(df.columns), Mode.faithful,
                            numeric=["units", "unit_price", "discount", "revenue"],
                            categorical=["region", "product", "channel"], datetime=["date"])
    log = []
    res = rengine.compute(recipe, SAMPLE, df, str(tmp_path / "assets"),
                          engine="r", log=log)
    assert res["engine"] == "r"
    failed = {sid: s["error"] for sid, s in res["sections"].items() if not s["ok"]}
    assert not failed, f"R sections failed: {failed}"


def test_r_engine_creative_methods(tmp_path):
    df = _df()
    recipe = ReportRecipe(mode=Mode.creative, sections=[
        Section(id="reg", heading="Drivers",
                analysis=AnalysisSpec(method="regression",
                                      variables=["revenue", "units", "unit_price", "discount"])),
        Section(id="fc", heading="Outlook",
                analysis=AnalysisSpec(method="timeseries_forecast",
                                      variables=["revenue"], time_var="date")),
        Section(id="ct", heading="Region x product",
                analysis=AnalysisSpec(method="crosstab", variables=["region", "product"])),
    ]).bounded(list(df.columns), Mode.creative)
    res = rengine.compute(recipe, SAMPLE, df, str(tmp_path / "assets"), engine="r", log=[])
    assert res["engine"] == "r"
    for sid in ("reg", "fc", "ct"):
        assert res["sections"][sid]["ok"], (sid, res["sections"][sid]["error"])
    # regression really computed an R-squared from the data
    assert res["sections"]["reg"]["numbers"].get("r_squared", 0) > 0.5
