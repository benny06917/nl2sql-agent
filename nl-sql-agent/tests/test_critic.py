
import sqlite3

import pytest
from langchain_core.messages import AIMessage

from app.agent import build_graph
from app.database import get_connection, get_schema


class FakeLLM:
    def __init__(self, responses):
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


def test_critic_approves_good_result(tmp_db):
    llm = FakeLLM([
        "SELECT COUNT(*) AS n FROM customers",
        '{"ok": true}',
        "There are 3 customers.",
    ])
    graph = build_graph(llm, tmp_db, max_retries=2, use_critic=True)
    result = graph.invoke({"question": "How many customers are there?",
                           "schema": _schema(tmp_db)})
    assert result["attempts"] == 1
    assert result["rows"] == [(3,)]
    assert result["critic_ok"] is True
    assert llm.calls == 3


def test_critic_triggers_rewrite_on_wrong_shape(tmp_db):

    llm = FakeLLM([
        "SELECT customer_city, COUNT(*) FROM customers GROUP BY customer_city",  # wrong shape, valid SQL
        '{"ok": false, "reason": "Question wants one number but many rows returned; remove GROUP BY and COUNT all rows."}',
        "SELECT COUNT(*) AS n FROM customers",                                    # fixed
        '{"ok": true}',
        "There are 3 customers.",
    ])
    graph = build_graph(llm, tmp_db, max_retries=2, use_critic=True)
    result = graph.invoke({"question": "How many customers are there in total?",
                           "schema": _schema(tmp_db)})
    assert result["attempts"] == 2          # the critic forced exactly one rewrite
    assert result["rows"] == [(3,)]
    assert result["critic_ok"] is True
    assert result["error"] is None
    assert llm.calls == 5


def test_critic_fails_open_on_unparseable_verdict(tmp_db):
    llm = FakeLLM([
        "SELECT COUNT(*) AS n FROM customers",
        "the result looks fine to me",       # not JSON
        "There are 3 customers.",
    ])
    graph = build_graph(llm, tmp_db, max_retries=2, use_critic=True)
    result = graph.invoke({"question": "How many customers are there?",
                           "schema": _schema(tmp_db)})
    assert result["attempts"] == 1           # no rewrite
    assert result["rows"] == [(3,)]
    assert llm.calls == 3


def test_critic_respects_retry_budget(tmp_db):
    llm = FakeLLM([
        "SELECT customer_city FROM customers",
        '{"ok": false, "reason": "nope"}',
        "SELECT customer_city FROM customers",
        '{"ok": false, "reason": "still nope"}',
        "Here is the best I could do.",
    ])
    graph = build_graph(llm, tmp_db, max_retries=1, use_critic=True)
    result = graph.invoke({"question": "How many customers are there?",
                           "schema": _schema(tmp_db)})
    assert result["attempts"] == 2           
    assert result["critic_ok"] is False     
    assert "best I could do" in result["answer"]
    assert llm.calls == 5


def test_critic_off_skips_the_node(tmp_db):
    llm = FakeLLM([
        "SELECT COUNT(*) AS n FROM customers",
        "There are 3 customers.",
    ])
    graph = build_graph(llm, tmp_db, max_retries=2, use_critic=False)
    result = graph.invoke({"question": "How many customers are there?",
                           "schema": _schema(tmp_db)})
    assert result["attempts"] == 1
    assert result["rows"] == [(3,)]
    assert llm.calls == 2
