
import argparse
import json
import math
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

QUESTIONS = Path(__file__).resolve().parent / "questions.json"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


# scoring
def _norm(value):
    if isinstance(value, str):
        text = value.strip()
        try:
            return float(text)                       
        except ValueError:
            return re.sub(r"[\s\-]+", "_", text.lower())   
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value            
    return value


def _tolerance(expected: float) -> float:
    text = repr(float(expected))
    decimals = len(text.split(".")[1]) if "." in text and not text.endswith(".0") else 0
    return 0.5 * 10 ** (-decimals) + 1e-9


def _values_equal(expected, actual) -> bool:
    numeric = (int, float)
    if isinstance(expected, numeric) and isinstance(actual, numeric) \
            and not isinstance(expected, bool) and not isinstance(actual, bool):
        if isinstance(expected, int):
            return actual == expected          
        return abs(actual - expected) <= _tolerance(expected)
    return expected == actual


def _row_matches(expected_row, actual_row) -> bool:
    pool = [_norm(v) for v in actual_row]
    for ev in (_norm(v) for v in expected_row):
        hit = next((i for i, av in enumerate(pool) if _values_equal(ev, av)), None)
        if hit is None:
            return False
        pool.pop(hit)
    return True


def rows_match(expected, actual) -> bool:

    if len(expected) != len(actual):
        return False
    remaining = list(actual)
    for erow in expected:
        hit = next((i for i, arow in enumerate(remaining) if _row_matches(erow, arow)), None)
        if hit is None:
            return False
        remaining.pop(hit)
    return True


# evaluation harness
def evaluate(graph, schema, items, delay=0.0, on_result=None):
    results = []
    for n, item in enumerate(items, start=1):
        start = time.perf_counter()
        record = {
            "id": item["id"],
            "difficulty": item["difficulty"],
            "question": item["question"],
            "expected": item["expected"],
        }
        try:
            out = graph.invoke({"question": item["question"], "schema": schema})
            actual = [list(r) for r in out.get("rows", [])]
            failed = bool(out.get("error"))
            record.update(
                sql=out.get("sql", ""),
                actual=actual,
                attempts=out.get("attempts", 1),
                agent_error=out.get("error"),
                correct=(not failed) and rows_match(item["expected"], actual),
            )
        except Exception as exc:  
            record.update(sql="", actual=[], attempts=0,
                          agent_error=f"{type(exc).__name__}: {exc}", correct=False,
                          infra_error=True)
        record["latency_s"] = round(time.perf_counter() - start, 2)
        results.append(record)
        if on_result:
            on_result(n, len(items), record)
        if delay and n < len(items):
            time.sleep(delay)
    return results


def summarise(results):
    def rate(rs):
        return (sum(r["correct"] for r in rs), len(rs))

    summary = {"overall": rate(results), "by_difficulty": {}}
    for level in ("easy", "medium", "hard"):
        subset = [r for r in results if r["difficulty"] == level]
        if subset:
            summary["by_difficulty"][level] = rate(subset)
    ran = [r for r in results if not r.get("infra_error")]
    summary["avg_attempts"] = round(sum(r["attempts"] for r in ran) / len(ran), 2) if ran else 0
    summary["avg_latency_s"] = round(sum(r["latency_s"] for r in results) / len(results), 2)
    summary["recovered"] = sum(1 for r in results if r["correct"] and r["attempts"] > 1)
    summary["infra_errors"] = sum(1 for r in results if r.get("infra_error"))
    return summary


def main():
    parser = argparse.ArgumentParser(description="Evaluate the SQL agent on the benchmark.")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="seconds to wait between questions (avoids rate limits)")
    parser.add_argument("--ids", nargs="*", help="only run these question ids, e.g. q16 q17")
    parser.add_argument("--questions", type=Path, default=QUESTIONS,
                        help="question file to run (default: eval/questions.json; "
                             "use eval/questions_holdout.json for the held-out set)")
    args = parser.parse_args()

    from rich.console import Console
    from rich.table import Table

    from app.agent import build_graph
    from app.config import get_llm, settings
    from app.database import get_connection, get_schema

    console = Console()
    items = json.loads(args.questions.read_text(encoding="utf-8"))
    if args.ids:
        items = [i for i in items if i["id"] in args.ids]

    conn = get_connection(settings.db_path)
    schema = get_schema(conn)
    conn.close()

    graph = build_graph(get_llm(), settings.db_path,
                        max_retries=settings.max_retries,
                        max_rows=settings.max_display_rows,
                        use_critic=settings.use_critic)

    console.print(f"[bold]Evaluating {len(items)} questions with model "
                  f"[cyan]{settings.model}[/cyan][/bold]  "
                  f"(critic: {'on' if settings.use_critic else 'off'}, "
                  f"retries: {settings.max_retries})\n")

    def show(n, total, r):
        mark = "[green]PASS[/green]" if r["correct"] else "[red]FAIL[/red]"
        console.print(f"{n:>2}/{total} {mark} {r['id']} [{r['difficulty']}] "
                      f"attempts={r['attempts']} {r['latency_s']}s")

    results = evaluate(graph, schema, items, delay=args.delay, on_result=show)
    summary = summarise(results)

    # report 
    console.print()
    table = Table(title="Execution accuracy", header_style="bold")
    table.add_column("Slice")
    table.add_column("Correct", justify="right")
    table.add_column("Accuracy", justify="right")
    c, t = summary["overall"]
    table.add_row("[bold]Overall[/bold]", f"{c}/{t}", f"{100 * c / t:.0f}%")
    for level, (c, t) in summary["by_difficulty"].items():
        table.add_row(level, f"{c}/{t}", f"{100 * c / t:.0f}%")
    console.print(table)
    console.print(f"Avg attempts: {summary['avg_attempts']}   "
                  f"Avg latency: {summary['avg_latency_s']}s   "
                  f"Recovered via self-correction: {summary['recovered']}   "
                  f"API/infra errors: {summary['infra_errors']}")

    failures = [r for r in results if not r["correct"]]
    if failures:
        console.print("\n[bold red]Failures[/bold red]")
        for r in failures:
            console.print(f"\n[bold]{r['id']}[/bold] {r['question']}")
            console.print(f"  expected: {r['expected']}")
            console.print(f"  got:      {r['actual']}")
            console.print(f"  sql:      {' '.join(r['sql'].split())}")
            if r.get("agent_error"):
                console.print(f"  error:    {r['agent_error']}")

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"model": settings.model, "summary": summary,
                               "results": results}, indent=2, default=str), encoding="utf-8")
    console.print(f"\nSaved full results to {out}")


if __name__ == "__main__":
    main()
