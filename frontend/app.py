"""
Streamlit frontend for Smart BI Agent
"""
import os
import sys
import json
from datetime import datetime

import streamlit as st
import pandas as pd

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(
    page_title="Smart BI Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .main-header { font-size: 2.5rem; font-weight: bold; color: #1f77b4; }
    .sub-header { font-size: 1.2rem; color: #666; }
    .sql-box { background-color: #f0f0f0; padding: 1rem; border-radius: 0.5rem; font-family: monospace; font-size: 0.9rem; }
    .metric-card { background-color: #f8f9fa; padding: 1rem; border-radius: 0.5rem; border-left: 4px solid #1f77b4; }
</style>
""", unsafe_allow_html=True)

def check_api():
    try:
        import requests
        response = requests.get(f"{API_URL}/health", timeout=5)
        return response.status_code == 200
    except:
        return False

def query_api(question: str):
    try:
        import requests
        response = requests.post(
            f"{API_URL}/query",
            json={"question": question, "enable_viz": True},
            timeout=60
        )
        return response.json()
    except Exception as e:
        return {"success": False, "error": str(e)}

def render_sidebar():
    with st.sidebar:
        st.markdown("### 📊 Smart BI Agent")
        st.markdown("Natural language data analytics powered by AI")
        st.divider()

        if check_api():
            st.success("🟢 API Connected")
        else:
            st.error("🔴 API Disconnected")
            st.info(f"Make sure the API is running at {API_URL}")

        st.divider()
        st.markdown("### 💡 Example Questions")
        examples = [
            "What was last month total sales",
            "East region category sales ranking",
            "Top 5 products with highest return rate",
            "Daily sales trend for last 30 days",
            "VIP level 4+ customer spending this month",
            "Sales proportion by channel",
            "Which brand has highest average order value in digital electronics",
            "How much did this month sales grow compared to last month"
        ]

        for ex in examples:
            if st.button(ex, key=f"ex_{ex[:20]}"):
                st.session_state.question = ex
                st.rerun()

        st.divider()
        st.markdown("### ⚙️ Settings")
        st.checkbox("Enable visualization", value=True, key="enable_viz")
        st.checkbox("Show SQL", value=True, key="show_sql")

def render_main():
    st.markdown('<p class="main-header">🤖 Smart BI Agent</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Ask anything about your business data in natural language</p>', unsafe_allow_html=True)

    col1, col2 = st.columns([4, 1])
    with col1:
        question = st.text_input(
            "Your question",
            placeholder="e.g., What was last month total sales?",
            key="question_input",
            value=st.session_state.get("question", "")
        )
    with col2:
        st.write("")
        st.write("")
        submit = st.button("🔍 Analyze", type="primary", use_container_width=True)

    if submit and question:
        with st.spinner("🤔 Thinking..."):
            result = query_api(question)

        if not result.get("success"):
            st.error(f"❌ Error: {result.get('error', 'Unknown error')}")
            return

        st.divider()
        st.markdown("### 📝 Answer")
        st.info(result["answer"])

        cols = st.columns(3)
        with cols[0]:
            st.metric("Execution Time", f"{result.get('execution_time_ms', 0):.0f} ms")
        with cols[1]:
            st.metric("Rows Returned", len(result.get("data", [])))
        with cols[2]:
            st.metric("SQL Generated", "✓" if result.get("sql") else "✗")

        if st.session_state.get("show_sql", True) and result.get("sql"):
            with st.expander("🔍 Generated SQL", expanded=False):
                st.code(result["sql"], language="sql")

        if result.get("data"):
            st.markdown("### 📋 Data")
            df = pd.DataFrame(result["data"])
            st.dataframe(df, use_container_width=True)

            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Download CSV",
                csv,
                f"query_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "text/csv"
            )

        viz = result.get("visualization")
        if viz and st.session_state.get("enable_viz", True):
            st.markdown("### 📈 Visualization")

            chart_type = viz.get("chart_type", "bar")
            x_col = viz.get("x_axis", "")
            y_col = viz.get("y_axis", "")

            if chart_type == "bar" and x_col and y_col:
                st.bar_chart(df.set_index(x_col)[y_col])
            elif chart_type == "line" and x_col and y_col:
                st.line_chart(df.set_index(x_col)[y_col])
            elif chart_type == "pie" and viz.get("category") and viz.get("value"):
                import plotly.express as px
                fig = px.pie(df, names=viz["category"], values=viz["value"], 
                           title=viz.get("title", ""))
                st.plotly_chart(fig, use_container_width=True)
            elif chart_type == "scatter" and x_col and y_col:
                import plotly.express as px
                fig = px.scatter(df, x=x_col, y=y_col, title=viz.get("title", ""))
                st.plotly_chart(fig, use_container_width=True)

def main():
    if "question" not in st.session_state:
        st.session_state.question = ""
    render_sidebar()
    render_main()

if __name__ == "__main__":
    main()
