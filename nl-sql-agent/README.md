# Retail SQL Agent

A natural-language-to-SQL agent that answers questions about an e-commerce
database by **writing SQL, running it, reading its own errors, and correcting
itself** — with no human in the loop. Built with LangGraph.

Ask a question in plain English:

```bash
python -m app.cli "What are the top 3 product categories by revenue?"
```

and the agent introspects the live schema, writes a query, executes it
(read-only), retries if it fails, and explains the result:

```
SQL (after 1 attempt(s))
  SELECT p.product_category, ROUND(SUM(oi.price),0) AS revenue
  FROM order_items oi JOIN products p ON p.product_id = oi.product_id
  GROUP BY p.product_category ORDER BY revenue DESC LIMIT 3

Answer
  Electronics is the top category by revenue at about $1.29M, far ahead of
  furniture and sports & leisure.
```

## Why an agent, and not just a chatbot?

For a single question against a schema you've already pasted into ChatGPT, you
don't need an agent. The agent earns its place when you remove the human:

- it **connects to the live database** and reads the schema itself — nothing is pasted,
- it **runs** the query and **reads the real error**, then **rewrites and retries**,
- it runs **unattended**, so a non-technical user (or a Slack bot) can drive it.

The honest boundary: for *known, repeated* questions, build a dashboard. This
agent is for the **long tail** of one-off questions nobody built a dashboard
for — self-serve analytics for people who can't write SQL.

## Architecture

```
          question
              │
              ▼
       ┌──────────────┐
       │ write_query  │ ◄──────────────┐   LLM: question + schema -> SQL
       └──────┬───────┘                │
              ▼                         │  feed the error back
       ┌──────────────┐                │
       │ execute_query│                │   tool: safety-gated, READ-ONLY
       └──────┬───────┘                │
              ▼                         │
     error AND retries left? ──────────┘
              │ no
              ▼
       ┌──────────────┐
       │   explain    │                    LLM: rows -> plain-English answer
       └──────┬───────┘
              ▼
             END
```

Two LLM-driven roles (**writer**, **explainer**) and one deterministic tool
(**executor**). The control flow is deterministic on purpose: we don't ask an
LLM whether an exception happened — we check. The LLM is used only where
judgement is actually needed.

## Project layout

```
retail-sql-agent/
├── app/
│   ├── config.py      # typed settings from .env (nothing hardcoded)
│   ├── database.py    # read-only connection, schema introspection, SQL safety gate
│   ├── state.py       # the typed state that flows through the graph
│   ├── prompts.py     # writer + explainer prompts
│   ├── agent.py       # the nodes, the self-correction loop, the graph
│   └── cli.py         # command-line entry point
├── data/
│   └── generate_data.py   # builds a synthetic, Olist-shaped retail.db (seeded)
├── tests/
│   ├── test_database.py   # safety gate, schema, execution (no LLM)
│   └── test_agent.py      # the full graph with a FAKE LLM (no network)
├── Dockerfile
├── requirements.txt
└── .github/workflows/ci.yml
```

## The data

`data/generate_data.py` builds a synthetic e-commerce database shaped like the
well-known [Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
dataset, but in English. Eight linked tables (`customers`, `sellers`,
`products`, `orders`, `order_items`, `payments`, `reviews`) — enough structure
that real questions require multi-table JOINs.

Generation is **seeded**, so the database is identical on every machine. Three
patterns are planted so analysis reveals something real:

| Pattern | What you'll find |
|---|---|
| Late deliveries get low reviews | ~1.95★ for late orders vs ~4.44★ on-time |
| One category dominates | electronics ≈ $1.29M revenue, 5× the runner-up |
| Growth over time | quarterly revenue trends upward across 2023–2024 |

Because the agent only talks to a SQL database, you can later drop in the **real
Olist CSVs** without changing a line of agent code — the data layer is
decoupled from the agent on purpose.

## Safety

Generated SQL is never trusted. Two independent layers:

1. **Safety gate** (`is_safe_sql`) — only a single `SELECT`/`WITH` statement is
   allowed; anything containing `DROP`, `DELETE`, `INSERT`, `UPDATE`, a second
   statement, etc. is rejected before it runs.
2. **Read-only connection** — the database is opened with SQLite's `mode=ro`,
   so even a query that slipped past the gate cannot modify data.

Both are covered by tests, including one that feeds the agent a `DROP TABLE`
and confirms the table survives.

## Quickstart

```bash
# 1. Install
pip install -r requirements.txt

# 2. Build the database (one time)
python data/generate_data.py

# 3. Add your key
cp .env.example .env            # then edit .env — free key at console.groq.com

# 4. Ask something
python -m app.cli "Which cities have the most customers?"
python -m app.cli "What is the average review score for late vs on-time deliveries?"
```

Run with Docker instead:

```bash
docker build -t retail-sql-agent .
docker run --env-file .env retail-sql-agent "Top 3 categories by revenue?"
```

## Tests

```bash
pytest -q        # 18 tests, no API key or network needed
```

The agent tests use a **fake LLM** that returns canned SQL, so the full
write → execute → retry → explain loop — including a case that fails twice and
recovers — is verified offline and in CI.

## Known limitations (and honest next steps)

- **No semantic validation.** The agent checks that a query *runs*, not that it
  answers the *right* question. A natural next step is an LLM "critic" node that
  judges whether the result matches the intent.
- **Single-turn.** It answers one question at a time; no conversational memory.
- **Synthetic data.** Realistic in shape, but generated — swap in real Olist
  data for a production-flavoured demo.
- **One model.** Uses Groq's Llama 3.3 70B; the model is a config value, so
  swapping providers is a one-line change.
