
import json

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from app import prompts
from app.database import UnsafeQueryError, execute_query, get_connection
from app.state import AgentState


def _strip_sql(text: str) -> str:
  
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lower().startswith("sql"):
            text = text[3:]
    return text.strip().rstrip(";").strip()


def _format_table(columns: list[str], rows: list[tuple]) -> str:
    
    if not columns:
        return "(no columns)"
    header = " | ".join(columns)
    body = "\n".join(" | ".join(str(v) for v in r) for r in rows)
    return f"{header}\n{body}" if body else f"{header}\n(no rows)"


def _parse_verdict(text: str) -> tuple[bool, str]:
 
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text.strip())
        return bool(data.get("ok", True)), str(data.get("reason", ""))
    except Exception:  # noqa: BLE001
        return True, ""


def build_graph(llm, db_path, max_retries: int = 2, max_rows: int = 50,
                use_critic: bool = True, critic_llm=None):

    critic_model = critic_llm or llm

    #  node: write
    def write_query(state: AgentState) -> dict:
        system = prompts.SQL_WRITER_SYSTEM.format(schema=state["schema"])
        if state.get("error"):                        
            system += prompts.SQL_RETRY_SUFFIX.format(
                previous_sql=state.get("sql", ""), error=state["error"])
        elif state.get("critic_feedback"):            
            system += prompts.SQL_CRITIC_SUFFIX.format(
                previous_sql=state.get("sql", ""), feedback=state["critic_feedback"])

        messages = [SystemMessage(system), HumanMessage(state["question"])]
        sql = _strip_sql(llm.invoke(messages).content)

        history = state.get("history", [])
        history.append({"attempt": state.get("attempts", 0) + 1, "sql": sql})
        return {
            "sql": sql,
            "attempts": state.get("attempts", 0) + 1,
            "history": history,
            "error": None,             
            "critic_feedback": None,
        }

    #  node: run 
    def execute(state: AgentState) -> dict:
        conn = get_connection(db_path)
        try:
            columns, rows = execute_query(conn, state["sql"], max_rows=max_rows)
            return {"columns": columns, "rows": rows, "error": None}
        except (UnsafeQueryError, Exception) as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}
        finally:
            conn.close()

    # node: critic 
    def critic(state: AgentState) -> dict:
        cols = state.get("columns", [])
        rows = state.get("rows", [])
        capped = " (capped)" if len(rows) >= max_rows else ""
        human = prompts.CRITIC_HUMAN.format(
            question=state["question"], sql=state["sql"],
            n_rows=len(rows), capped=capped, columns=cols,
            preview=_format_table(cols, rows[:10]),
        )
        raw = critic_model.invoke(
            [SystemMessage(prompts.CRITIC_SYSTEM), HumanMessage(human)]).content
        ok, reason = _parse_verdict(raw)
        return {
            "critic_ok": ok,
            "critic_feedback": None if ok else (reason or "Result does not match the question."),
        }

    # conditional edges
    def route_after_execute(state: AgentState) -> str:
        if state.get("error"):
            return "retry" if state["attempts"] < max_retries + 1 else "explain"
        return "critic" if use_critic else "explain"

    def route_after_critic(state: AgentState) -> str:
        if not state.get("critic_ok", True) and state["attempts"] < max_retries + 1:
            return "retry"
        return "explain"

    #node: explain
    def explain(state: AgentState) -> dict:
        if state.get("error"):
            return {"answer": (
                "I couldn't produce a working query after "
                f"{state['attempts']} attempts. Last error: {state['error']}")}
        table = _format_table(state.get("columns", []), state.get("rows", []))
        human = prompts.EXPLAIN_HUMAN.format(
            question=state["question"], sql=state["sql"],
            n_rows=len(state.get("rows", [])), result_table=table)
        messages = [SystemMessage(prompts.EXPLAIN_SYSTEM), HumanMessage(human)]
        return {"answer": llm.invoke(messages).content}

    # the graph 
    builder = StateGraph(AgentState)
    builder.add_node("write_query", write_query)
    builder.add_node("execute_query", execute)
    builder.add_node("explain", explain)

    builder.set_entry_point("write_query")
    builder.add_edge("write_query", "execute_query")

    exec_map = {"retry": "write_query", "explain": "explain"}
    if use_critic:
        builder.add_node("critic", critic)
        exec_map["critic"] = "critic"
        builder.add_conditional_edges(
            "critic", route_after_critic,
            {"retry": "write_query", "explain": "explain"})
    builder.add_conditional_edges("execute_query", route_after_execute, exec_map)
    builder.add_edge("explain", END)

    return builder.compile()
