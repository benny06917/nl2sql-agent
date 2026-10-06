
import sqlite3

import pytest

from app.database import (
    UnsafeQueryError,
    execute_query,
    get_connection,
    get_schema,
    is_safe_sql,
)


@pytest.fixture
def tmp_db(tmp_path):
    # create a temporary SQLite database with a simple table for testing
    path = tmp_path / "mini.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE customers (customer_id INTEGER, customer_city TEXT);
        INSERT INTO customers VALUES (1, 'Austin'), (2, 'Boston');
        """
    )
    conn.commit()
    conn.close()
    return str(path)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM customers",
    "select customer_city from customers where customer_id = 1",
    "WITH c AS (SELECT * FROM customers) SELECT * FROM c",
])
def test_safe_queries_allowed(sql):
    assert is_safe_sql(sql) is True


@pytest.mark.parametrize("sql", [
    "DROP TABLE customers",
    "DELETE FROM customers",
    "UPDATE customers SET customer_city='x'",
    "INSERT INTO customers VALUES (3, 'x')",
    "SELECT 1; DROP TABLE customers",         # piggy-backed statement
    "SELECT * FROM customers; DELETE FROM customers",
    "",                                        # empty
])
def test_unsafe_queries_blocked(sql):
    assert is_safe_sql(sql) is False


# schema introspection
def test_get_schema_lists_table_and_columns(tmp_db):
    conn = get_connection(tmp_db)
    schema = get_schema(conn)
    conn.close()
    assert "customers(" in schema
    assert "customer_city" in schema


# execution 
def test_execute_returns_rows(tmp_db):
    conn = get_connection(tmp_db)
    columns, rows = execute_query(conn, "SELECT customer_city FROM customers ORDER BY customer_id")
    conn.close()
    assert columns == ["customer_city"]
    assert rows == [("Austin",), ("Boston",)]


def test_execute_rejects_unsafe(tmp_db):
    conn = get_connection(tmp_db)
    with pytest.raises(UnsafeQueryError):
        execute_query(conn, "DROP TABLE customers")
    conn.close()


def test_connection_is_read_only(tmp_db):
    """Even if the safety gate were bypassed, the connection itself blocks writes."""
    conn = get_connection(tmp_db)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO customers VALUES (9, 'x')")
    conn.close()
