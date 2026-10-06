
import sqlite3

import pytest
from langchain_core.messages import AIMessage

from app.agent import build_graph
from app.database import get_connection, get_schema


class FakeLLM:

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        return AIMessage(content=self._responses.pop(0))


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "mini.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE customers (customer_id INTEGER, customer_city TEXT);
        INSERT INTO customers VALUES (1, 'Austin'), (2, 'Austin'), (3, 'Boston');
        """
    )
    conn.commit()
    conn.close()
    return str(path)


def _schema(db_path):
    conn = get_connection(db_path)
    s = get_schema(conn)
    conn.close()
    return s


def test_happy_path(tmp_db):
    llm = FakeLLM([
        "SELECT customer_city, COUNT(*) AS n FROM customers GROUP BY customer_city ORDER BY n DESC",
        "Austin has the most customers, with 2.",
    ])
    graph = build_graph(llm, tmp_db, max_retries=2, use_critic=False)
    result = graph.invoke({"question": "Which city has the most customers?",
                           "schema": _schema(tmp_db)})

    assert result["attempts"] == 1
    assert result["error"] is None
    assert ("Austin", 2) in result["rows"]
    assert "Austin" in result["answer"]
    assert llm.calls == 2


def test_self_correction(tmp_db):
    llm = FakeLLM([
        "SELECT nonexistent_column FROM customers",          # fails
        "SELECT COUNT(*) AS total FROM customers",           # fixed
        "There are 3 customers in total.",                   # explanation
    ])
    graph = build_graph(llm, tmp_db, max_retries=2, use_critic=False)
    result = graph.invoke({"question": "How many customers are there?",
                           "schema": _schema(tmp_db)})

    assert result["attempts"] == 2          # it retried exactly once
    assert result["error"] is None          # and recovered
    assert result["rows"] == [(3,)]
    assert len(result["history"]) == 2      # both attempts recorded
    assert llm.calls == 3


def test_retry_budget_exhausted(tmp_db):
    llm = FakeLLM([
        "SELECT bad1 FROM customers",
        "SELECT bad2 FROM customers",
        "SELECT bad3 FROM customers",
    ])
    graph = build_graph(llm, tmp_db, max_retries=2, use_critic=False)
    result = graph.invoke({"question": "broken question",
                           "schema": _schema(tmp_db)})

    assert result["attempts"] == 3          # initial + 2 retries
    assert result["error"] is not None
    assert "couldn't produce a working query" in result["answer"]


def test_unsafe_sql_is_caught(tmp_db):
    llm = FakeLLM([
        "DROP TABLE customers",                 
        "SELECT COUNT(*) AS total FROM customers",
        "There are 3 customers.",
    ])
    graph = build_graph(llm, tmp_db, max_retries=2, use_critic=False)
    result = graph.invoke({"question": "count customers",
                           "schema": _schema(tmp_db)})

    # The table still exists and we recovered with a safe query.
    assert result["rows"] == [(3,)]
    conn = get_connection(tmp_db)
    assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 3
    conn.close()
