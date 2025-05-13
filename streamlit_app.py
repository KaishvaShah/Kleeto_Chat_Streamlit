# kleeto_chat_ui.py
import streamlit as st
import requests
import uuid
import json
from typing import Dict, Any
import pandas as pd
import altair as alt        # v5+ is fine
# --------------------------------------------------------------------
# 👉 1.  CONSTANTS  – move these into environment variables in prod  –
# --------------------------------------------------------------------
API_URL   = "https://2r8bdovc24.execute-api.eu-north-1.amazonaws.com/kleeto-lambda-function"
JWT_TOKEN = (
    "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJ1c2VyX2lkIjoiNTE3MzVkNTEtNjM5OS00OGUxLWI4YmItMWFkMDIyMjUzNTFjIn0."
    "timLrhoINEPPY6Q0PcfQNBTApUA-D--WtN_8uN6ZuLM"
)
USER_ID   = "51735d51-6399-48e1-b8bb-1ad02225351c"

CUSTOMER_MAP = {
    ("customer_1", "compliance"): "ea2a946d-76a7-4dde-b010-cb93ad300fa2",
    ("customer_1", "inventory") : "3308d012-ce0f-4eff-a60d-a2dcc1eed570",
    ("customer_2", "compliance"): "5c931a9e-0c1a-4557-8bde-08409a1f1e03",
    ("customer_2", "inventory") : "61f389ea-fedd-49b7-946f-48378ed3bdb7",
}

# --------------------------------------------------------------------
# 👉 2.  INITIAL SESSION STATE
# --------------------------------------------------------------------
# 1. Initializing session state for chat_id
if "messages" not in st.session_state:
    st.session_state.messages: list[Dict[str, str]] = []   # {"role": "user/assistant", "text": "..."}
    
# Check if chat_id exists, if not, set it to "" (on a new chat or session start)
if "chat_id" not in st.session_state or not st.session_state.chat_id:
    st.session_state.chat_id = ""

# 2. Sidebar for new chat functionality
with st.sidebar:
    st.title("📊 Kleeto Chat Assistant")
    customer = st.selectbox("Customer", ["customer_1", "customer_2"])
    table_name = st.selectbox("Table", ["inventory", "compliance"])
    customer_id = CUSTOMER_MAP[(customer, table_name)]

    # "New chat" button - this resets the session chat history and chat_id
    if st.button("🔄 New chat"):
        st.session_state.messages.clear()
        st.session_state.chat_id = ""  # Reset chat_id when starting a new chat

# 3. Helper function to call the Lambda
def call_kleeto_api(question: str, customer_id: str):
    payload = {
        "path": "/chat/response",
        "body": {
            "chat_id": st.session_state.chat_id or "",  # Send empty chat_id if it's new
            "user_id": USER_ID,
            "customer_id": customer_id,
            "message": question,
        },
    }
    headers = {
        "authorization": JWT_TOKEN,
        "content-type": "application/json",
    }

    resp = requests.post(API_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    inner = resp.json()  # Final payload from the backend
    print("Inner: ", inner)

    # Extract data from the backend response
    raw_content = inner.get("content", "")
    chart_config = inner.get("chart_config")  # May be None
    rows = None
    if raw_content and isinstance(raw_content, str):
        try:
            rows = json.loads(raw_content)  # [{"A":…,"B":…},…]
        except json.JSONDecodeError:
            pass  # Leave rows = None on failure

    answer = inner.get("summarized_output") or raw_content or "⚠️ Backend returned no user‑visible text."
    chat_id = inner.get("chat_id", "")
    print("Chat ID: ", chat_id)

    return answer, rows, chart_config, chat_id

# def build_chart(df: pd.DataFrame, cfg: dict) -> alt.Chart:
#     ctype = cfg.get("chart_type")

#     if ctype == "grouped_bar":
#         # Expecting exactly ONE entry in chart_series
#         s = cfg["chart_series"][0]
#         x_col = s["label_column"]
#         y_col = s["value_column"]

#         # optional grouping by another column
#         group_col = cfg.get("multi_bar_filter_column")
#         if group_col and group_col.lower() != "none":
#             chart = (
#                 alt.Chart(df)
#                 .mark_bar()
#                 .encode(
#                     x=alt.X(f"{x_col}:N", title=x_col),
#                     y=alt.Y(f"{y_col}:Q", title=y_col),
#                     color=alt.Color(f"{group_col}:N", title=group_col)
#                 )
#             )
#         else:  # simple single‑series bars
#             chart = (
#                 alt.Chart(df)
#                 .mark_bar()
#                 .encode(
#                     x=alt.X(f"{x_col}:N", title=x_col),
#                     y=alt.Y(f"{y_col}:Q", title=y_col)
#                 )
#             )

#     else:
#         # fallback visual if an unknown chart_type arrives
#         chart = (
#             alt.Chart(df.head(1))
#             .mark_text()
#             .encode(text=alt.value(f"⚠️ unsupported chart_type: {ctype}"))
#         )

#     if cfg.get("chart_title"):
#         chart = chart.properties(title=cfg["chart_title"])
#     return chart

# ------------- chart builder ---------------------------------------------------
# ---------- FIXED build_chart --------------------------------------------------
def build_chart(df: pd.DataFrame, cfg: dict) -> alt.Chart:
    """
    Render an Altair chart from the dataframe and Kleeto chart_config.
    Supports BAR, GROUPED_BAR, STACKED_BAR, PIE, LINE, SCATTER, MULTI_BAR.
    """
    ctype   = cfg.get("chart_type", "").lower()
    title   = cfg.get("chart_title") or cfg.get("title")
    subtitle= cfg.get("chart_subtitle") or cfg.get("subtitle")
    group_col_cfg = cfg.get("multi_bar_filter_column")
    series_cfg    = cfg.get("series", cfg.get("chart_series", []))

    # -------- 1. melt into long format ----------------------------------------
    frames = []
    for s in series_cfg:
        lab = s["label_column"]
        val = s["value_column"]
        tmp = df[[lab, val]].copy()
        tmp.rename(columns={lab: "label", val: "value"}, inplace=True)
        tmp["series"] = s["series_name"]
        if group_col_cfg and group_col_cfg.lower() != "none":
            tmp["group"] = df[group_col_cfg]
        frames.append(tmp)

    if not frames:
        raise ValueError("chart_config.series is empty")

    dfl = pd.concat(frames, ignore_index=True)

    # -------- 2. choose mark & encodings --------------------------------------
    if ctype == "bar":
        chart = (
            alt.Chart(dfl)
            .mark_bar()
            .encode(
                x=alt.X("label:N", title=series_cfg[0]["label_column"]),
                y=alt.Y("value:Q", title=series_cfg[0]["value_column"]),
                tooltip=["label:N", "value:Q"],
            )
        )

    elif ctype in {"grouped_bar", "multi_bar"}:
        colour_field = (
            "group:N"
            if group_col_cfg and group_col_cfg.lower() != "none"
            else "series:N"
        )
        chart = (
            alt.Chart(dfl)
            .mark_bar()
            .encode(
                x=alt.X("label:N", title=series_cfg[0]["label_column"]),
                y=alt.Y("value:Q", title=series_cfg[0]["value_column"]),
                color=alt.Color(colour_field, title=colour_field.split(":")[0]),
                tooltip=["series:N", "value:Q"],
            )
        )

    elif ctype == "stacked_bar":
        chart = (
            alt.Chart(dfl)
            .mark_bar()
            .encode(
                x=alt.X("label:N", title=series_cfg[0]["label_column"]),
                y=alt.Y("value:Q", stack="zero", title=series_cfg[0]["value_column"]),
                color=alt.Color("series:N", title="series"),
                tooltip=["series:N", "value:Q"],
            )
        )

    elif ctype == "pie":
        chart = (
            alt.Chart(dfl)
            .mark_arc()
            .encode(
                theta=alt.Theta("value:Q"),
                color=alt.Color("label:N"),
                tooltip=["label:N", "value:Q"],
            )
        )

    elif ctype == "line":
        chart = (
            alt.Chart(dfl)
            .mark_line(point=True)
            .encode(
                x=alt.X("label:N", title=series_cfg[0]["label_column"]),
                y=alt.Y("value:Q", title=series_cfg[0]["value_column"]),
                color=alt.Color("series:N", title="series"),
            )
        )

    elif ctype == "scatter":
        chart = (
            alt.Chart(dfl)
            .mark_circle(size=100)
            .encode(
                x=alt.X("label:N", title=series_cfg[0]["label_column"]),
                y=alt.Y("value:Q", title=series_cfg[0]["value_column"]),
                color=alt.Color("series:N", title="series"),
                tooltip=["series:N", "value:Q"],
            )
        )

    else:  # unsupported
        return (
            alt.Chart(
                pd.DataFrame(
                    {"msg": [f"⚠️ unsupported chart_type: {ctype}"]}
                )
            )
            .mark_text()
            .encode(text="msg")
        )

    # -------- 3. titles -------------------------------------------------------
    if title:
        chart = chart.properties(title=title)
    if subtitle:
        chart = chart.properties(title={"text": title or "", "subtitle": subtitle})

    return chart

# --------------------------------------------------------------------
# 👉 5.  MAIN CHAT WINDOW
# --------------------------------------------------------------------
# -----------------------------------------------
#  main chat loop  (put this where your old block was)
# -----------------------------------------------
# 4. Main chat window
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["text"])

question = st.chat_input("Ask me anything about the data…")
if question:
    # 1. Show the user's message immediately
    with st.chat_message("user"):
        st.markdown(question)
    st.session_state.messages.append({"role": "user", "text": question})

    # 2. Call backend and render the assistant reply
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                answer, rows, chart_cfg, maybe_chat_id = call_kleeto_api(question, customer_id)

                # Only update chat_id if the backend returns a new one
                if maybe_chat_id:
                    st.session_state.chat_id = maybe_chat_id
            except Exception as e:
                answer, rows, chart_cfg = f"❌ Error: {e}", None, None

        # Natural language summary
        st.markdown(answer)

        # Table
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True)

            # Chart
            if chart_cfg:  # Use the backend's config
                chart = build_chart(df, chart_cfg)
                st.altair_chart(chart, use_container_width=True)
            else:  # Quick fallback (same as before)
                if {"Document_Status", "Employee_Count"}.issubset(df.columns):
                    st.bar_chart(df.set_index("Document_Status")["Employee_Count"])

    # 3. Persist the assistant message in history
    st.session_state.messages.append({"role": "assistant", "text": answer})
