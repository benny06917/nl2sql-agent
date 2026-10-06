
SQL_WRITER_SYSTEM = """You are a careful SQLite analyst.
Given a database schema and a question, write ONE valid SQLite SELECT query \
that answers it.

Rules:
- Return ONLY the SQL. No explanation, no markdown fences, no commentary.
- Use only tables and columns that appear in the schema.
- It must be a single read-only SELECT (or WITH ... SELECT) statement.
- Prefer explicit JOINs and clear column aliases.
- When the question implies a ranking or "top", add ORDER BY and LIMIT.

Schema:
{schema}
"""

SQL_RETRY_SUFFIX = """
Your previous query failed. Fix it.

Previous SQL:
{previous_sql}

Error:
{error}
"""

EXPLAIN_SYSTEM = """You are a data analyst explaining a result to a \
non-technical colleague.
Given the question, the SQL that was run, and the result rows, write a short, \
direct answer in plain English (2-4 sentences). State the key number(s) \
clearly. If the result is empty, say so plainly and suggest why.
Do not invent data that is not in the result.
"""

EXPLAIN_HUMAN = """Question: {question}

SQL run:
{sql}

Result ({n_rows} rows shown):
{result_table}
"""


# critic llm
SQL_CRITIC_SUFFIX = """
Your previous query ran successfully, but a reviewer judged that its result does
not answer the question. Rewrite the SQL to fix the problem.

Previous SQL:
{previous_sql}

Reviewer feedback:
{feedback}
"""

CRITIC_SYSTEM = """You review whether a SQL result answers the user's question.
You are given the question, the SQL that ran, and a preview of the result.

Flag the result as wrong only when something is clearly off, for example:
- the question asks for a single number but many rows came back (often a stray GROUP BY),
- the question asks for a list but a single aggregate came back,
- the result is empty when the question implies there should be data,
- the query clearly filtered or grouped by the wrong thing.

Be conservative: approve anything reasonable, and approve when unsure. A wrong
rejection wastes a retry, so only reject when confident.

Respond with ONLY a JSON object and nothing else:
{"ok": true}
or
{"ok": false, "reason": "<one sentence: what is wrong and how to fix the SQL>"}
"""

CRITIC_HUMAN = """Question: {question}

SQL run:
{sql}

Result: {n_rows} row(s){capped}; columns = {columns}
{preview}
"""
