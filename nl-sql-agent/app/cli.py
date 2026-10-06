
import argparse

from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule
from rich.table import Table

from app.agent import build_graph
from app.config import get_llm, settings
from app.database import get_connection, get_schema

console = Console()


def _print_result(columns, rows):
    if not columns:
        console.print("[dim](no columns returned)[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    for col in columns:
        table.add_column(str(col))
    for row in rows[:20]:
        table.add_row(*[str(v) for v in row])
    console.print(table)


def main():
    parser = argparse.ArgumentParser(description="Ask the retail database a question.")
    parser.add_argument("question", type=str, help="Your question in plain English.")
    args = parser.parse_args()

    # Load the live schema once and inject it into the run.
    conn = get_connection(settings.db_path)
    schema = get_schema(conn)
    conn.close()

    llm = get_llm()
    graph = build_graph(
        llm, settings.db_path,
        max_retries=settings.max_retries,
        max_rows=settings.max_display_rows,
        use_critic=settings.use_critic,
    )

    console.print(Rule(f"[bold cyan]Q: {args.question}[/bold cyan]"))
    result = graph.invoke({"question": args.question, "schema": schema})

    console.print("\n[bold]SQL[/bold] "
                  f"[dim](after {result.get('attempts', 1)} attempt(s))[/dim]")
    console.print(Markdown(f"```sql\n{result.get('sql', '')}\n```"))

    console.print("\n[bold]Result[/bold]")
    _print_result(result.get("columns", []), result.get("rows", []))

    console.print("\n[bold green]Answer[/bold green]")
    console.print(result.get("answer", ""))


if __name__ == "__main__":
    main()
