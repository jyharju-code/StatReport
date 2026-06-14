"""Tests for the recipe safety layer — the analog of EditMyRaw's clamping tests."""

from statreport.recipe import (AnalysisSpec, Mode, ReportRecipe, Section,
                               neutral_recipe)


def test_bounded_drops_unknown_columns():
    recipe = ReportRecipe(sections=[Section(
        id="s1", heading="X",
        analysis=AnalysisSpec(method="comparison", variables=["revenue", "ghost"],
                              group_by="region"))])
    bounded = recipe.bounded(["revenue", "region"], Mode.faithful)
    a = bounded.sections[0].analysis
    assert "ghost" not in a.variables
    assert a.variables == ["revenue"]
    assert a.group_by == "region"


def test_bounded_drops_unknown_group_by():
    recipe = ReportRecipe(sections=[Section(
        id="s1", heading="X",
        analysis=AnalysisSpec(method="comparison", variables=["revenue"], group_by="nope"))])
    bounded = recipe.bounded(["revenue"], Mode.faithful)
    # comparison without a valid group_by degrades to descriptive
    assert bounded.sections[0].analysis.method == "descriptive"


def test_faithful_mode_forbids_creative_methods():
    recipe = ReportRecipe(sections=[Section(
        id="s1", heading="reg",
        analysis=AnalysisSpec(method="regression", variables=["a", "b"]))])
    bounded = recipe.bounded(["a", "b"], Mode.faithful)
    assert bounded.sections[0].analysis.method == "descriptive"  # not allowed in faithful


def test_creative_mode_allows_regression():
    recipe = ReportRecipe(sections=[Section(
        id="s1", heading="reg",
        analysis=AnalysisSpec(method="regression", variables=["a", "b"]))])
    bounded = recipe.bounded(["a", "b"], Mode.creative)
    assert bounded.sections[0].analysis.method == "regression"


def test_unknown_chart_and_table_normalised():
    recipe = ReportRecipe(sections=[Section(
        id="s1", heading="X",
        analysis=AnalysisSpec(method="descriptive", chart="rainbow", table="weird"))])
    a = recipe.bounded(["a"], Mode.faithful).sections[0].analysis
    assert a.chart == "none"
    assert a.table == "summary"


def test_section_cap():
    secs = [Section(id=f"s{i}", heading="h",
                    analysis=AnalysisSpec(method="descriptive")) for i in range(30)]
    bounded = ReportRecipe(sections=secs).bounded(["a"], Mode.faithful)
    assert len(bounded.sections) <= 12


def test_neutral_recipe_builds_real_sections():
    recipe = neutral_recipe(["revenue", "units", "region", "date"], Mode.faithful,
                            numeric=["revenue", "units"], categorical=["region"],
                            datetime=["date"])
    methods = {s.analysis.method for s in recipe.sections}
    assert "descriptive" in methods
    assert "correlation" in methods   # >=2 numerics
    assert "comparison" in methods    # numeric + categorical
    assert recipe.sections  # non-empty
