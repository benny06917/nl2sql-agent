
import time

import pandas as pd
import streamlit as st

from app.agent import build_graph
from app.config import get_llm, settings
from app.database import get_connection, get_schema

# ----------------------------------------------------------------------
# Page + theme
# ----------------------------------------------------------------------
st.set_page_config(
    page_title="SQL Agent",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS. The config.toml already guarantees a readable dark base; this
# layer adds the polish. Every text colour here is explicit so nothing ever
# renders as white-on-white.
st.markdown(
    """
    <style>
    :root {
        --bg:      #0b0e14;
        --panel:   #141a24;
        --panel-2: #0f141c;
        --border:  #253044;
        --text:    #e6edf3;
        --muted:   #9aa7b8;
        --a1:      #6366f1;   /* indigo */
        --a2:      #22d3ee;   /* cyan   */
        --ok:      #34d399;
        --warn:    #fbbf24;
        --err:     #f87171;
    }

    .stApp { background: radial-gradient(1200px 600px at 10% -10%, #10192b 0%, var(--bg) 55%); }

    /* ---- Hero header ---- */
    .hero-title {
        font-size: 2.6rem; font-weight: 800; line-height: 1.1; margin: 0;
        background: linear-gradient(135deg, var(--a1), var(--a2));
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    .hero-sub { color: var(--muted); font-size: 1.05rem; margin-top: .35rem; }
    .pill {
        display:inline-block; padding: 3px 12px; border-radius: 999px;
        font-size: .78rem; font-weight: 600; letter-spacing:.02em;
        border: 1px solid var(--border); color: var(--muted);
        background: var(--panel-2); margin-right: 6px;
    }
    .pill-live { color: var(--ok); border-color: #1f5f45; }
    .pill-live::before { content:"● "; color: var(--ok); }

    /* ---- Cards ---- */
    .card {
        background: var(--panel); border: 1px solid var(--border);
        border-radius: 14px; padding: 1.1rem 1.25rem; margin-bottom: 1rem;
        box-shadow: 0 8px 30px rgba(0,0,0,.25);
    }
    .card h4 { margin: 0 0 .5rem 0; color: var(--text); font-size: .95rem;
               text-transform: uppercase; letter-spacing: .06em; }
    .answer-card {
        background: linear-gradient(180deg, rgba(99,102,241,.10), rgba(34,211,238,.04));
        border: 1px solid #2b3a63; border-left: 4px solid var(--a1);
        border-radius: 14px; padding: 1.1rem 1.25rem;
        color: var(--text); font-size: 1.06rem; line-height: 1.6;
    }

    /* ---- Buttons ---- */
    .stButton > button {
        border-radius: 10px; border: 1px solid var(--border);
        background: var(--panel); color: var(--text); font-weight: 600;
        transition: all .15s ease;
    }
    .stButton > button:hover {
        border-color: var(--a1); color: #fff;
        box-shadow: 0 0 0 1px var(--a1), 0 6px 18px rgba(99,102,241,.25);
    }
    /* Primary run button */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, var(--a1), var(--a2));
        border: none; color: #0a0e16;
    }
    .stButton > button[kind="primary"]:hover { filter: brightness(1.08); color:#0a0e16; }

    /* ---- Metrics ---- */
    [data-testid="stMetricValue"] { color: var(--text); font-weight: 700; }
    [data-testid="stMetricLabel"] { color: var(--muted); }

    /* ---- Sidebar ---- */
    [data-testid="stSidebar"] { background: var(--panel-2); border-right: 1px solid var(--border); }
    [data-testid="stSidebar"] * { color: var(--text); }

    /* ---- Inputs ---- */
    .stTextInput > div > div > input {
        background: var(--panel-2); color: var(--text); border: 1px solid var(--border);
    }
    code, pre, .stCode { font-size: .9rem; }

    /* Log lines in the live pipeline */
    .log { font-family: ui-monospace, Menlo, monospace; font-size: .9rem;
           line-height: 1.9; color: var(--text); }
    .log .t { color: var(--muted); }
    .log .ok { color: var(--ok); } .log .warn { color: var(--warn); }
    .log .err { color: var(--err); } .log .acc { color: var(--a2); }
    </style>
    """,
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------------
# Resources (cached so we don't rebuild on every interaction)
# ----------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def load_schema():
    conn = get_connection(settings.db_path)
    schema = get_schema(conn)
    # structured view for the sidebar
    tables = {}
    for (t,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall():
        cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
        tables[t] = [(c[1], c[2]) for c in cols]
    conn.close()
    return schema, tables


@st.cache_resource(show_spinner=False)
def load_graph(max_retries: int):
    """Returns (graph, error_message). error_message is None on success."""
    try:
        llm = get_llm()
        graph = build_graph(
            llm, settings.db_path,
            max_retries=max_retries,
            max_rows=settings.max_display_rows,
        )
        return graph, None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


try:
    schema_str, tables = load_schema()
    db_ok = True
except Exception as exc:  # noqa: BLE001
    schema_str, tables, db_ok = "", {}, False


# ----------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ◆ SQL Agent")
    st.caption("Natural language → SQL, with self-correction.")

    st.divider()
    st.markdown("#### Connection")
    if db_ok:
        st.markdown(
            f"<span class='pill pill-live'>database connected</span>"
            f"<span class='pill'>read-only</span>",
            unsafe_allow_html=True,
        )
    else:
        st.error("Database not found. Run: `python data/generate_data.py`")

    st.markdown("#### Settings")
    max_retries = st.slider("Self-correction retries", 0, 4, settings.max_retries)
    st.markdown(
        f"<span class='pill'>model: {settings.model}</span>",
        unsafe_allow_html=True,
    )

    if tables:
        st.markdown("#### Schema")
        for t, cols in tables.items():
            with st.expander(f"{t}  ·  {len(cols)} cols"):
                st.markdown(
                    "\n".join(f"- `{c}` <span class='t'>{ty}</span>"
                              for c, ty in cols),
                    unsafe_allow_html=True,
                )

    st.divider()
    st.caption("Built with LangGraph · Groq · SQLite")


# ----------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------
st.markdown('<p class="hero-title">Ask your database anything</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="hero-sub">An AI agent that writes SQL, runs it, fixes its own '
    'mistakes, and explains the answer — no SQL required.</p>',
    unsafe_allow_html=True,
)

# Example questions
EXAMPLES = [
    "What are the top 3 product categories by revenue?",
    "What is the average review score for late vs on-time deliveries?",
    "Which cities have the most customers?",
    "How has monthly revenue changed over 2023 and 2024?",
    "What percentage of delivered orders arrived late?",
]

if "question" not in st.session_state:
    st.session_state.question = EXAMPLES[0]

st.markdown("<br>", unsafe_allow_html=True)
cols = st.columns(len(EXAMPLES))
for i, ex in enumerate(EXAMPLES):
    if cols[i].button(ex, key=f"ex{i}", use_container_width=True):
        st.session_state.question = ex

question = st.text_input(
    "Your question",
    value=st.session_state.question,
    label_visibility="collapsed",
)
run = st.button("▶  Run agent", type="primary", disabled=not db_ok)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def to_df(columns, rows):
    if not columns:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=columns)


def maybe_chart(df: pd.DataFrame):
    """Auto bar chart for small 2-column results with a numeric second column."""
    if df.shape[1] == 2 and 1 <= len(df) <= 25:
        y = df.columns[1]
        if pd.api.types.is_numeric_dtype(df[y]):
            st.bar_chart(df.set_index(df.columns[0]))


# ----------------------------------------------------------------------
# Run
# ----------------------------------------------------------------------
if run and question.strip():
    graph, graph_err = load_graph(max_retries)

    if graph is None:
        st.error(
            "Could not start the agent — most likely GROQ_API_KEY is missing.\n\n"
            f"Details: {graph_err}"
        )
        st.stop()

    st.markdown("<br>", unsafe_allow_html=True)

    # Live pipeline log
    st.markdown("#### Live pipeline")
    log_box = st.empty()
    log_lines: list[str] = []

    def log(msg: str):
        log_lines.append(msg)
        log_box.markdown(
            "<div class='card'><div class='log'>" + "<br>".join(log_lines)
            + "</div></div>",
            unsafe_allow_html=True,
        )

    t0 = time.time()
    final_state = {"question": question, "schema": schema_str}

    log("<span class='t'>›</span> starting run…")
    for chunk in graph.stream(
        {"question": question, "schema": schema_str},
        stream_mode="updates",
    ):
        for node, update in chunk.items():
            final_state.update(update)

            if node == "write_query":
                n = update.get("attempts", "?")
                sql_preview = " ".join(update.get("sql", "").split())[:90]
                log(f"<span class='acc'>✍ write_query</span> "
                    f"attempt {n} — <span class='t'>{sql_preview}…</span>")

            elif node == "execute_query":
                if update.get("error"):
                    log(f"<span class='err'>✖ execute_query</span> "
                        f"failed: <span class='t'>{update['error'][:120]}</span>")
                    log("<span class='warn'>↻ retrying with the error fed back…</span>")
                else:
                    nrows = len(update.get("rows", []))
                    log(f"<span class='ok'>✔ execute_query</span> "
                        f"ok — {nrows} row(s) returned")

            elif node == "critic":
                if update.get("critic_ok"):
                    log("<span class='ok'>✔ critic</span> result looks right")
                else:
                    log(f"<span class='warn'>⚠ critic</span> rejected: "
                        f"<span class='t'>{(update.get('critic_feedback') or '')[:110]}</span>")
                    log("<span class='warn'>↻ rewriting to fix the result…</span>")

            elif node == "explain":
                log("<span class='acc'>💬 explain</span> composing answer…")

    elapsed = time.time() - t0
    log(f"<span class='ok'>● done</span> in {elapsed:.1f}s")

    # ---- Results ----
    attempts = final_state.get("attempts", 1)
    df = to_df(final_state.get("columns", []), final_state.get("rows", []))

    st.markdown("<br>", unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Attempts", attempts, help="How many times it wrote SQL (>1 means it self-corrected)")
    m2.metric("Rows returned", len(df))
    m3.metric("Latency", f"{elapsed:.1f}s")
    m4.metric("Status", "recovered" if attempts > 1 else "clean")

    # Answer
    st.markdown("#### Answer")
    st.markdown(
        f"<div class='answer-card'>{final_state.get('answer', '')}</div>",
        unsafe_allow_html=True,
    )

    # SQL + result side by side
    st.markdown("<br>", unsafe_allow_html=True)
    left, right = st.columns([1, 1])
    with left:
        st.markdown("#### Generated SQL")
        st.code(final_state.get("sql", ""), language="sql")
    with right:
        st.markdown("#### Result")
        if df.empty:
            st.info("No rows returned.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
            maybe_chart(df)
            st.download_button(
                "⬇ Download CSV",
                df.to_csv(index=False).encode(),
                file_name="result.csv",
                mime="text/csv",
            )

    # Self-correction detail
    history = final_state.get("history", [])
    if len(history) > 1:
        with st.expander(f"🔁 Self-correction trace ({len(history)} attempts)"):
            for h in history:
                st.markdown(f"**Attempt {h['attempt']}**")
                st.code(h["sql"], language="sql")

elif run:
    st.warning("Type a question first.")
