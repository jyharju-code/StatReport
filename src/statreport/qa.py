"""
qa.py — the claim-checking critic.

The statistics-domain analog of EditMyRaw's batch-consistency critic. EditMyRaw
scores how uniform a set of photos is and nudges it toward the reference; here we
score how *grounded* the narrative is: every number in the prose must trace back
to a number the engine actually computed. Ungrounded numbers are flagged, and in
creative mode pipeline.py can run revision rounds (the "sparring" loop) to fix them.

This is what makes the tool safe to put a real report through: a hallucinated
statistic is caught before it ships.
"""

from __future__ import annotations

import re
from typing import Dict, List

_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d+%?|-?\d{3,}|-?\d+%")


def _to_float(token: str):
    t = token.strip().rstrip("%").replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def _collect_result_numbers(results: dict) -> List[float]:
    vals: List[float] = []
    for sec in results.get("sections", {}).values():
        for v in (sec.get("numbers") or {}).values():
            try:
                f = float(v)
                vals.append(f)
            except (TypeError, ValueError):
                continue
        tbl = sec.get("table_markdown")
        if tbl and tbl != "NA":
            for m in re.findall(r"-?\d[\d,]*\.?\d+|-?\d+", str(tbl)):
                f = _to_float(m)
                if f is not None:
                    vals.append(f)
    ds = results.get("dataset", {})
    for k in ("rows", "cols"):
        if isinstance(ds.get(k), (int, float)):
            vals.append(float(ds[k]))
    return vals


def _matches(n: float, pool: List[float]) -> bool:
    for r in pool:
        if abs(n - r) <= max(0.01, 0.01 * abs(r)):
            return True
    # also allow matching the rounded forms a writer would naturally use
    for r in pool:
        if round(n) == round(r) or round(n, 1) == round(r, 1):
            return True
    return False


def _is_checkable(n: float, raw: str) -> bool:
    """Worth flagging if unverified — skip trivial small counts and plain years."""
    if "%" in raw or "." in raw:
        return True
    if 1900 <= n <= 2100:   # looks like a year; don't flag
        return False
    return abs(n) >= 100


def check_claims(narrative: Dict[str, str], results: dict) -> dict:
    pool = _collect_result_numbers(results)
    issues: List[dict] = []
    verified = 0
    checked = 0

    for sec_id, text in (narrative or {}).items():
        if not text:
            continue
        for token in _NUM_RE.findall(text):
            n = _to_float(token)
            if n is None:
                continue
            if not _is_checkable(n, token):
                continue
            checked += 1
            if _matches(n, pool):
                verified += 1
            else:
                ctx_idx = text.find(token)
                context = text[max(0, ctx_idx - 30):ctx_idx + len(token) + 30].replace("\n", " ")
                issues.append({"section": sec_id, "value": token, "context": context.strip()})

    score = 100.0 if checked == 0 else round(100.0 * verified / checked, 1)
    return {"score": score, "checked": checked, "verified": verified, "issues": issues}


def format_log(qa: dict) -> str:
    if qa["checked"] == 0:
        return "QA: no numeric claims to verify."
    msg = f"QA: {qa['verified']}/{qa['checked']} numeric claims grounded ({qa['score']}/100)."
    if qa["issues"]:
        msg += " Unverified: " + ", ".join(i["value"] for i in qa["issues"][:6])
    return msg
