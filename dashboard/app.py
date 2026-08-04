"""Streamlit dashboard: browse the whole knowledge base and quiz yourself.

Run with:
    streamlit run dashboard/app.py
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Allow running via `streamlit run dashboard/app.py` from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import DATA_DIR  # noqa: E402
from database.knowledge_base import KnowledgeBase  # noqa: E402
from embeddings.rag import LocalRAG  # noqa: E402

st.set_page_config(page_title="Company Trivia Intelligence", layout="wide")


def _available_companies() -> list[str]:
    if not DATA_DIR.exists():
        return []
    return sorted(p.name.replace("-", " ").title() for p in DATA_DIR.iterdir() if p.is_dir())


st.sidebar.title("Company Trivia Intelligence")
companies = _available_companies()
default_idx = companies.index("Galderma") if "Galderma" in companies else 0
company = st.sidebar.selectbox("Company", companies, index=default_idx if companies else 0) if companies else st.sidebar.text_input("Company", "Galderma")

if not company:
    st.stop()

kb = KnowledgeBase(company)
summary = kb.summary()
st.sidebar.markdown("### Knowledge base size")
st.sidebar.json(summary)

tabs = st.tabs([
    "Company Overview", "Products", "Leadership", "Timeline",
    "Instagram Insights", "YouTube Insights", "Latest News",
    "Quiz Generator", "Ask Anything",
])

# ------------------------------------------------------------------ Overview
with tabs[0]:
    st.header(f"{company} — Company Overview")
    facts = kb.load("facts", default=[])
    website = kb.load("website", default=[])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Pages crawled", len(website))
    col2.metric("Facts extracted", len(facts))
    col3.metric("Products found", len(kb.load("products", default=[])))
    col4.metric("Timeline events", len(kb.load("timeline", default=[])))

    st.subheader("Key facts")
    for category in ("founding", "focus", "scale"):
        cat_facts = [f["text"] for f in facts if f.get("category") == category]
        if cat_facts:
            st.markdown(f"**{category.title()}**")
            for f in cat_facts[:5]:
                st.write(f"- {f}")

    if facts:
        st.subheader("All facts")
        st.dataframe(pd.DataFrame(facts), use_container_width=True)

# ------------------------------------------------------------------ Products
with tabs[1]:
    st.header("Products")
    products = kb.load("products", default=[])
    if products:
        df = pd.DataFrame(products)
        cat_filter = st.multiselect("Filter by category", sorted(df["category"].unique()))
        if cat_filter:
            df = df[df["category"].isin(cat_filter)]
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No products scraped yet. Run the pipeline first.")

# ---------------------------------------------------------------- Leadership
with tabs[2]:
    st.header("Leadership")
    leaders = kb.load("leaders", default=[])
    if leaders:
        st.dataframe(pd.DataFrame(leaders), use_container_width=True)
    else:
        st.info("No leadership data scraped yet.")

# ------------------------------------------------------------------ Timeline
with tabs[3]:
    st.header("Company Timeline")
    timeline = kb.load("timeline", default=[])
    if timeline:
        df = pd.DataFrame(timeline).sort_values("year")
        importance_color = {"high": "🔴", "medium": "🟡", "low": "⚪"}
        for _, row in df.iterrows():
            st.markdown(f"**{row['year']}** {importance_color.get(row['importance'], '')} — {row['event']}")
    else:
        st.info("No timeline events scraped yet.")

# ----------------------------------------------------------- Instagram tab
with tabs[4]:
    st.header("Instagram Insights")
    posts = kb.load("instagram", default=[])
    if posts:
        df = pd.DataFrame(posts)
        col1, col2 = st.columns(2)
        col1.metric("Posts collected", len(df))
        if "likes" in df and df["likes"].notna().any():
            col2.metric("Avg. likes", int(df["likes"].dropna().mean()))
        all_hashtags = [h for tags in df.get("hashtags", []) for h in tags]
        if all_hashtags:
            st.subheader("Top hashtags")
            st.bar_chart(pd.Series(all_hashtags).value_counts().head(15))
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No Instagram data scraped yet (profile may be private or rate-limited).")

# ------------------------------------------------------------- YouTube tab
with tabs[5]:
    st.header("YouTube Insights")
    videos = kb.load("youtube", default=[])
    if videos:
        df = pd.DataFrame(videos)
        col1, col2 = st.columns(2)
        col1.metric("Videos collected", len(df))
        if "view_count" in df and df["view_count"].notna().any():
            col2.metric("Total views", int(df["view_count"].dropna().sum()))
        st.dataframe(df[["title", "upload_date", "view_count", "comment_count"]], use_container_width=True)
    else:
        st.info("No YouTube data scraped yet.")

# ---------------------------------------------------------------- News tab
with tabs[6]:
    st.header("Latest News")
    news = kb.load("news", default=[])
    if news:
        for item in news[:40]:
            st.markdown(f"**[{item['headline']}]({item['url']})**")
            st.caption(f"{item.get('publication', '')} · {item.get('date', '')}")
            st.write(item.get("summary", ""))
            st.divider()
    else:
        st.info("No news collected yet.")

# ---------------------------------------------------------- Quiz Generator
with tabs[7]:
    st.header("Quiz Generator")
    quiz = kb.load("quiz", default=[])
    if quiz:
        difficulty = st.selectbox("Difficulty", ["easy", "medium", "hard", "very_hard"])
        pool = [q for q in quiz if q["difficulty"] == difficulty]
        if pool:
            if st.button("New question"):
                st.session_state["quiz_q"] = random.choice(pool)
            q = st.session_state.get("quiz_q") or random.choice(pool)
            st.subheader(q["question"])
            if q["q_type"] == "mcq":
                choice = st.radio("Choose one:", q["options"])
                if st.button("Reveal answer"):
                    st.success(f"Correct answer: {q['answer']}") if choice == q["answer"] else st.error(f"Correct answer: {q['answer']}")
            else:
                st.text_input("Your answer")
                if st.button("Reveal answer", key="reveal_other"):
                    st.info(f"Answer: {q['answer']}")
        else:
            st.warning("No questions at this difficulty yet.")
        st.subheader("Full quiz bank")
        st.dataframe(pd.DataFrame(quiz), use_container_width=True)
    else:
        st.info("No quiz generated yet. Run the pipeline first.")

# --------------------------------------------------------------- Ask Anything
with tabs[8]:
    st.header("Ask Anything")
    st.caption("Answers are retrieved only from the scraped knowledge base and cite their source.")
    question = st.text_input("Your question", placeholder="What is Galderma's newest injectable?")
    if question:
        rag = LocalRAG(company)
        result = rag.ask(question)
        st.write(result.answer)
        if result.citations:
            st.caption("Sources: " + ", ".join(result.citations))
