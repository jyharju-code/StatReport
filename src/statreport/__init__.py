"""StatReport — example + data -> a statistical report, the EditMyRaw way.

Give an **example report** (a look to imitate), a **prompt** (a description of the
report you want), or a **combination** of both, plus your **data** — and StatReport
returns a finished statistical report.

Core principle (the statistics-domain analog of EditMyRaw's "clamp every value"):
the LLM never produces a number. R (or the Python fallback) computes every figure;
the LLM only chooses the report *recipe* and writes the prose around verified output.
"""

__version__ = "0.1.0"
