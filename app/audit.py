"""
Run every question against both companies and check the answers for the mistakes that a
passing test suite does not catch.

run_questions.py checks the twenty questions give the verdict the answer key says they
should. That is necessary and it is not enough. It says nothing about whether the headline
answers the question that was asked, whether a refusal contradicts its own reason, whether
the figures on screen trace to anything, or whether the picture beside the number has
anything to do with it.

So this walks every metric, with every combination of parameters the data actually offers,
and applies the checks below. Anything it flags is a real defect or a deliberate decision
that needs a comment explaining itself.

    python -m app.audit            summary and every finding
    python -m app.audit --dump     the full record, for a human or another agent to read
"""

import itertools
import json
import re
import sys
import traceback

from . import answer, db, definitions, metrics

# Every metric has to have a picture, or a stated reason it does not need one. These are
# the ones where a chart would be noise: a single figure with nothing to compare it to.
NO_VISUAL_NEEDED = {"vendor_capacity", "item_period_comparison"}

# Parameter values are never invented. They come from what the tenant actually has, the
# same way the console builds its dropdowns.
SAMPLE = 3                       # how many values of each option to try
PER_METRIC = 12                  # and how many combinations to keep per metric


def options(tid):
    def col(sql, key):
        return [r[key] for r in db.fetch(tid, sql)]
    months = []
    y, m = metrics.TODAY.year, metrics.TODAY.month
    for _ in range(14):
        months.append("%d-%02d" % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return {
        "tender": col("SELECT tender_ref FROM src_tender_award ORDER BY window_end DESC", "tender_ref"),
        "plant": col("SELECT DISTINCT plant FROM src_tender_award ORDER BY plant", "plant"),
        "grade": col("SELECT DISTINCT grade_code FROM src_tender_award ORDER BY grade_code", "grade_code"),
        "vendor": col("SELECT ledger_name FROM src_tally_ledger "
                      "WHERE parent_group = 'Sundry Creditors' ORDER BY ledger_name", "ledger_name"),
        "month": months,
        "fy": ["FY23-24", "FY24-25", "FY25-26", "FY26-27"],
        "int": [12], "float": [0.30], "vendor_opt": [None],
        "material": col("SELECT code FROM item WHERE kind = 'feedstock' ORDER BY code", "code"),
    }


DEFAULTS = {"months": 12, "weeks": 8, "tonnes": 3000, "quoted_gcv": 3200,
            "margin_per_gcv": 0.30}


def cases(tid, spec, opts):
    """Every combination worth trying, capped so this stays a test and not a crawl."""
    keys, pools = [], []
    for key, _label, kind in spec.get("params", []):
        keys.append(key)
        if key in DEFAULTS and kind in ("int", "float"):
            pools.append([DEFAULTS[key]])
        else:
            vals = opts.get(kind) or [None]
            pools.append(vals[:SAMPLE] if len(vals) > SAMPLE else vals)
    if not keys:
        return [{}]
    return [dict(zip(keys, combo)) for combo in itertools.product(*pools)][:PER_METRIC]


NUMERAL = re.compile(r"\d")


def check(tid, name, spec, params, a, visual_metrics):
    """Everything that can be wrong with an answer without the verdict being wrong."""
    bad = []
    # A refusal with no declared derivation falls back to showing the figures themselves,
    # and the console can only show a figure it has a name for. R2 reached a customer
    # reading "unk 538.4" and "lo 6,490.6", which looks like an audit trail and cannot be
    # followed. Either give the answer a working list, or give the figure a label.
    if not a.get("working"):
        for k, v in (a.get("numbers") or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0:
                if k not in _panel_labels():
                    bad.append(("a figure with no name",
                                f"'{k}' would appear in the derivation panel as a bare "
                                f"identifier, because this answer declares no working and "
                                f"the console has no label for it"))
    verdict = a.get("verdict")
    head, sub, text = a.get("head") or "", a.get("sub") or "", a.get("text") or ""
    nums = a.get("numbers") or {}

    def known(figure):
        """Does this figure trace to something a query returned?

        The same value gets printed several ways: 1,63,824 or 163824.0, and money in the
        short form as 16.38 Cr for 16,38,24,466. All of those are the same number and none
        of them is a fabrication, so all of them count as traced."""
        want = figure.replace(",", "")
        for v in nums.values():
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            for scale in (1.0, 1e5, 1e7):        # rupees, lakhs, crores
                g = f / scale
                for dp in (0, 1, 2, 3):
                    if f"{abs(g):.{dp}f}".rstrip("0").rstrip(".") == want.rstrip("0").rstrip("."):
                        return True
                    if f"{abs(g):.{dp}f}" == want:
                        return True
        return False

    if a.get("gate_failed"):
        bad.append(("gate", a["gate_failed"]))

    if not head:
        bad.append(("no headline", "nothing for the eye to land on"))
    if not sub:
        bad.append(("no subline", "the headline stands with no explanation"))

    # a headline figure that no query produced is the whole thing this product exists to
    # prevent, and the gate only reads the body text
    # a calendar label is not a measurement, the same rule the egress gate uses
    head_scan = answer.DATE_LABEL.sub("", head)
    for figure in re.findall(r"\d[\d,]*(?:\.\d+)?", head_scan):
        if len(figure.replace(",", "").replace(".", "")) > 2 and not known(figure):
            bad.append(("headline figure not traced", f"{figure!r} in head {head!r}"))

    # a refusal whose headline is a zero is almost always the wrong figure picked
    if verdict == "withheld" and re.match(r"^0\b", head.strip()):
        bad.append(("refusal headline is zero",
                    f"head {head!r} with reason {a.get('reason')!r}"))

    if verdict == "withheld":
        if not a.get("reason"):
            bad.append(("refusal with no reason", "nothing tells the reader why"))
        if not a.get("fix") and "not in the planning window" not in text:
            bad.append(("refusal with no way forward", "nothing says what would fix it"))

    if verdict == "answered":
        if not a.get("working"):
            bad.append(("no audit trail", "answered with no derivation shown"))
        if NUMERAL.search(text) and not nums:
            bad.append(("figures with no source", "text has numerals, numbers is empty"))
        if name not in visual_metrics and name not in NO_VISUAL_NEEDED:
            bad.append(("no visual", "nothing in visualFor draws this metric"))

    if not a.get("sql") and verdict == "answered":
        bad.append(("no query recorded", "answered without recording what ran"))

    # the same figure twice in the headline and subline reads as a mistake
    hn = re.findall(r"\d[\d,]*(?:\.\d+)?", head)
    sn = re.findall(r"\d[\d,]*(?:\.\d+)?", sub)
    if hn and hn == sn:
        bad.append(("headline repeated in subline", head))

    return bad


def chart_functions():
    """Every chart the dispatcher names has to exist.

    Deleting dead code by slicing between two markers took nine live chart functions out
    with it, twice, and the page parsed cleanly both times: a missing function is only an
    error at the moment somebody calls it, which is while a customer is looking at it."""
    import pathlib
    html = (pathlib.Path(__file__).resolve().parent / "web" / "index.html").read_text(
        encoding="utf-8")
    js = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
    body = js[js.index("function visualFor("):js.index("const KW=")]

    defined = set(re.findall(r"function\s+(\w+)\s*\(", js))
    defined |= set(re.findall(r"(?:const|let|var)\s+(\w+)\s*=", js))
    called = set(re.findall(r"([a-zA-Z_][A-Za-z0-9_]*)\s*\(", body))
    builtin = {"if", "for", "while", "switch", "catch", "return", "typeof", "function",
               "some", "map", "filter", "find", "slice", "reduce", "forEach", "join",
               "push", "concat", "split", "replace", "test", "match", "round", "max",
               "min", "abs", "toFixed", "includes", "indexOf", "sort", "keys", "values",
               "entries", "isArray", "isInteger", "parseInt", "parseFloat", "isFinite",
               "appendChild", "querySelector", "addEventListener", "setAttribute",
               "getAttribute", "toLocaleString", "trim", "every", "from", "error",
               "Math", "Number", "String", "Object", "Array", "JSON", "Set", "Date"}
    return [(c, "the chart dispatcher calls it and it is not defined anywhere")
            for c in sorted(called - defined - builtin)]


_NUMNAME = None


def _panel_labels():
    """The labels the console can put on a figure in the derivation panel."""
    global _NUMNAME
    if _NUMNAME is None:
        import pathlib
        html = (pathlib.Path(__file__).resolve().parent / "web" / "index.html").read_text(
            encoding="utf-8")
        m = re.search(r"const NUMNAME=\{(.*?)\};", html, re.S)
        _NUMNAME = set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*:", m.group(1))) if m else set()
    return _NUMNAME


def resolved_dispatches():
    """A query that attributes a load to a contract must read the decision, not the source.

    src_dispatch_register.tender_ref is only what the register happened to write down. It is
    blank on exactly the loads that matter, and both the canonical layer and the review queue
    put the answer somewhere else: dispatch_tender. A query that joins the raw column alone
    silently ignores every placement ever made, by rule or by a person.

    order_book did this. The refusal underneath it counted the unplaced loads correctly, so
    answering one moved the counter from five to four and the console said "Recomputing" -
    and the tonnage never moved, because the credit landed in a column the sum was not
    reading. Sixty two loads placed by rule were invisible to it too, so the order book was
    overstated by about four thousand tonnes before anybody had touched anything.

    Judged one SQL statement at a time, not one metric at a time. order_book named
    dispatch_tender in its unplaced-loads query while both of its summing queries ignored it,
    so the first version of this check - which asked whether the metric mentioned the table
    anywhere - passed while the bug was live. It failed to catch the one bug it existed for.

    The statements are read out of the parse tree rather than matched with a regex. The
    second version paired triple quotes by hand, mispaired a docstring with the next query,
    and started reporting the Python between two statements as though it were SQL. Two wrong
    checks before a right one is worth leaving in the comment.

    Narrow on purpose: only a statement mentioning tender_ref is attributing loads to
    contracts at all. dispatch_total, realised_price and item_period_comparison read the
    register and filter by plant, or by product and date, so a load's contract is none of
    their business and they are correctly left alone."""
    import ast
    import pathlib
    path = pathlib.Path(__file__).resolve().parent / "metrics.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    out = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        name = None
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and getattr(dec.func, "id", None) == "metric"
                    and dec.args and isinstance(dec.args[0], ast.Constant)):
                name = dec.args[0].value
        if name is None:
            continue
        body = list(node.body)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]                                   # the docstring is not SQL
        for sub in body:
            for lit in ast.walk(sub):
                if not (isinstance(lit, ast.Constant) and isinstance(lit.value, str)):
                    continue
                # a comment can name the right table while the SQL does the wrong thing
                sql = re.sub(r"--[^\n]*", "", lit.value)
                if "SELECT" not in sql or "src_dispatch_register" not in sql:
                    continue
                if "tender_ref" not in sql or "dispatch_tender" in sql:
                    continue
                out.append((name,
                            "one of its queries attributes loads to contracts from "
                            "src_dispatch_register.tender_ref alone, so every placement the "
                            "review queue and the canonical layer recorded is invisible "
                            "to it"))
                break
            else:
                continue
            break
    return out


def console_contract():
    """The console and the metric registry have to agree, and nothing was checking that.

    Three times now a mismatch has shipped: a chart guard reading a key that had been
    renamed, so the headline question drew nothing; a bar reading a field that did not
    exist, so every segment was NaN; and a month parameter with no entry in the kind map,
    so the sentence rendered a number box and sent 2026 where it meant 2026-10.

    None of those fail a test that only asks the server questions, because the server is
    fine. They fail because the two halves were edited at different times."""
    import pathlib
    html = (pathlib.Path(__file__).resolve().parent / "web" / "index.html").read_text(
        encoding="utf-8")
    bad = []

    kind_block = html[html.index("const KIND="):html.index("const DEFAULTV=")]
    kinds = set(re.findall(r"(\w+):'(?:int|float|month|tender|grade|plant|vendor|vendor_opt"
                           r"|material|fy)'", kind_block))
    sent_block = html[html.index("const SENT="):html.index("const KIND=")]
    for name, spec in metrics.REGISTRY.items():
        if f"{name}:[" not in sent_block:
            bad.append((name, "no sentence in the console, so it cannot be asked"))
        for key, _label, _kind in spec.get("params", []):
            if key not in kinds:
                bad.append((name, f"parameter {key!r} has no entry in KIND, so it renders "
                                  f"as a number box and sends the wrong type"))
    return bad


def visual_metrics():
    """Which metrics the interface actually draws something for."""
    import pathlib
    html = (pathlib.Path(__file__).resolve().parent / "web" / "index.html").read_text(
        encoding="utf-8")
    body = html[html.index("function visualFor("):html.index("const KW=")]
    return set(re.findall(r"m===['\"]([a-z_]+)['\"]", body))


def main(dump=False):
    vis = visual_metrics()
    findings, ran, record = [], 0, []
    for name, detail in console_contract() + chart_functions() + resolved_dispatches():
        findings.append(("-", name, {}, [("console and registry disagree", detail)]))
    for tid in [r["tenant_id"] for r in db.tenants()]:
        defs = definitions.load(tid)
        opts = options(tid)
        for name, spec in metrics.REGISTRY.items():
            for params in cases(tid, spec, opts):
                ran += 1
                try:
                    a = answer.run(tid, name, params)
                except Exception:                                  # noqa: BLE001
                    findings.append((tid, name, params, [("crash", traceback.format_exc(
                        limit=2).strip().splitlines()[-1])]))
                    continue
                bad = check(tid, name, spec, params, a, vis)
                if bad:
                    findings.append((tid, name, params, bad))
                if dump:
                    record.append({
                        "tenant": tid, "metric": name, "title": spec.get("title"),
                        "params": params, "verdict": a.get("verdict"),
                        "head": a.get("head"), "sub": a.get("sub"), "text": a.get("text"),
                        "reason": a.get("reason"), "fix": a.get("fix"),
                        "working": a.get("working"),
                        "numbers": {k: (float(v) if isinstance(v, (int, float)) else v)
                                    for k, v in (a.get("numbers") or {}).items()},
                        "rows": (a.get("rows") or [])[:3],
                        "queries": len(a.get("sql") or []),
                        "has_visual": name in vis,
                        "follows": spec.get("follows", []),
                    })

    if dump:
        out = "audit_dump.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=1, default=str)
        print(f"  wrote {out}: {len(record)} answers")

    print()
    print(f"  {ran} answers checked across every metric and both companies")
    if not findings:
        print("  nothing to fix")
        return 0
    by_kind = {}
    for tid, name, params, bad in findings:
        for kind, detail in bad:
            by_kind.setdefault(kind, []).append((tid, name, params, detail))
    print(f"  {sum(len(v) for v in by_kind.values())} problems in "
          f"{len(findings)} answers\n")
    for kind, items in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        print(f"  {kind}  ({len(items)})")
        for tid, name, params, detail in items[:6]:
            print(f"      {tid} {name} {params}")
            print(f"        {detail[:150]}")
        if len(items) > 6:
            print(f"      and {len(items) - 6} more")
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main(dump="--dump" in sys.argv))
