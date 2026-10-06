
import importlib.util
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from app.agent import build_graph
from app.database import get_connection, get_schema

_spec = importlib.util.spec_from_file_location(
    "run_eval", Path(__file__).resolve().parent.parent / "eval" / "run_eval.py"
)
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)

QUESTIONS = Path(__file__).resolve().parent.parent / "eval" / "questions.json"
DB = Path(__file__).resolve().parent.parent / "data" / "retail.db"


# scorer
def test_exact_match():
    assert run_eval.rows_match([[2000]], [(2000,)])


def test_wrong_number_fails():
    assert not run_eval.rows_match([[2000]], [(1999,)])


def test_rounding_tolerance():
    assert run_eval.rows_match([["late", 1.95]], [("late", 1.9469)])


def test_row_order_ignored():
    assert run_eval.rows_match([["a", 1], ["b", 2]], [("b", 2), ("a", 1)])


def test_extra_columns_allowed():
    assert run_eval.rows_match([["electronics"]], [("electronics", 1290651.0)])


def test_label_formatting_ignored():
    assert run_eval.rows_match([["on_time", 4.44]], [("On-time", 4.4446)])


def test_year_string_vs_int():
    assert run_eval.rows_match([["2023", 952497.0]], [(2023, 952497.0)])


def test_row_count_mismatch_fails():
    assert not run_eval.rows_match([[33], [47], [71]], [(33,), (47,)])


def test_wrong_value_in_right_shape_fails():
    assert not run_eval.rows_match([["electronics"]], [("furniture", 1290651.0)])


class GoldLLM:

    def __init__(self, gold_by_question, wrong_ids=()):
        self.gold = gold_by_question
        self.wrong_ids = set(wrong_ids)

    def invoke(self, messages):
        system, human = messages[0].content, messages[1].content
        if "SQLite analyst" in system:                    
            for q, (qid, sql) in self.gold.items():
                if q == human:
                    return AIMessage(content="SELECT 0" if qid in self.wrong_ids else sql)
        return AIMessage(content="explanation")          


@pytest.mark.skipif(not DB.exists(), reason="run data/generate_data.py first")
def test_harness_scores_perfect_and_wrong_agents():
    items = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    gold = {i["question"]: (i["id"], i["gold_sql"]) for i in items}

    conn = get_connection(str(DB))
    schema = get_schema(conn)
    conn.close()

 
    graph = build_graph(GoldLLM(gold), str(DB), max_retries=0, use_critic=False)
    results = run_eval.evaluate(graph, schema, items)
    assert run_eval.summarise(results)["overall"] == (20, 20)

    graph = build_graph(GoldLLM(gold, wrong_ids={"q01", "q16"}), str(DB), max_retries=0, use_critic=False)
    results = run_eval.evaluate(graph, schema, items)
    assert run_eval.summarise(results)["overall"] == (18, 20)


def test_count_must_match_exactly():
    assert not run_eval.rows_match([[2000]], [(1999,)])
    assert not run_eval.rows_match([[2000]], [(2001,)])


def test_unrounded_value_accepted_when_question_asked_for_rounding():
    assert run_eval.rows_match([[2093918.0]], [(2093917.62,)])


def test_value_off_by_more_than_rounding_fails():
    assert not run_eval.rows_match([[2093918.0]], [(2093930.0,)])
    assert not run_eval.rows_match([[24.7]], [(25.0,)])


def test_fraction_instead_of_percentage_fails():
    assert not run_eval.rows_match([[24.7]], [(0.247,)])


def test_one_decimal_rounding_accepted():
    assert run_eval.rows_match([[24.7]], [(24.68,)])
