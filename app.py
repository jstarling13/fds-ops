"""
app.py
Financial Document Studio — Lead Intelligence Agent Dashboard
Streamlit Frontend

Run: streamlit run app.py
"""

import os
import logging
import sqlite3
from datetime import datetime

import streamlit as st
import pandas as pd
from dotenv import load_dotenv

from lead_agent import run_lead_agent, init_db, fetch_all_leads, mark_outreach_sent

# Load .env on startup
load_dotenv()

# Configure logging visible in terminal during dev
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="FDS | Lead Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CUSTOM CSS — clean, institutional aesthetic
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* Suppress default Streamlit padding */
    .block-container { padding-top: 1.5rem; padding-bottom: 1rem; }

    /* Score badge colors */
    .score-high  { background: #16a34a; color: white; padding: 2px 10px; border-radius: 12px; font-weight: 600; font-size: 0.85rem; }
    .score-mid   { background: #d97706; color: white; padding: 2px 10px; border-radius: 12px; font-weight: 600; font-size: 0.85rem; }
    .score-low   { background: #dc2626; color: white; padding: 2px 10px; border-radius: 12px; font-weight: 600; font-size: 0.85rem; }

    /* Outreach copy boxes */
    .outreach-box {
        background: #f8fafc;
        border-left: 3px solid #1e40af;
        padding: 1rem 1.2rem;
        border-radius: 0 8px 8px 0;
        font-size: 0.9rem;
        white-space: pre-wrap;
        font-family: 'Courier New', monospace;
    }
    .linkedin-box {
        background: #f0f9ff;
        border-left: 3px solid #0284c7;
        padding: 1rem 1.2rem;
        border-radius: 0 8px 8px 0;
        font-size: 0.9rem;
        white-space: pre-wrap;
        font-family: 'Courier New', monospace;
    }

    /* Metric card override */
    [data-testid="metric-container"] {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1rem;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# SIDEBAR — CONFIG & NAVIGATION
# ---------------------------------------------------------------------------
with st.sidebar:
    st.image("https://via.placeholder.com/180x40/1e3a5f/ffffff?text=FDS", width=180)
    st.markdown("### Lead Intelligence Agent")
    st.caption("Version 1.0 | Internal Use Only")
    st.divider()

    page = st.radio(
        "Navigation",
        ["New Lead", "Lead Pipeline", "Settings"],
        label_visibility="collapsed",
    )

    st.divider()
    st.caption(f"Last refresh: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")

    # API status indicators
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    tavily_key = os.getenv("TAVILY_API_KEY", "")

    st.markdown("**API Status**")
    st.markdown(
        f"{'🟢' if anthropic_key else '🔴'} Anthropic {'Connected' if anthropic_key else 'Not Set'}"
    )
    st.markdown(
        f"{'🟢' if tavily_key else '🟡'} Tavily {'Connected' if tavily_key else 'Optional — Not Set'}"
    )


# ---------------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------------

def score_badge(score: int) -> str:
    if score >= 7:
        return f'<span class="score-high">{score}/10</span>'
    elif score >= 4:
        return f'<span class="score-mid">{score}/10</span>'
    else:
        return f'<span class="score-low">{score}/10</span>'


def get_db_connection():
    return init_db("data/leads.db")


# ---------------------------------------------------------------------------
# PAGE: NEW LEAD
# ---------------------------------------------------------------------------
if page == "New Lead":
    st.title("Research a New Lead")
    st.caption(
        "Enter a founder and company. The agent will research them, score their ICP fit, "
        "and generate personalized outreach — no generic templates."
    )
    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        founder_name = st.text_input(
            "Founder Full Name *",
            placeholder="e.g., Sarah Chen",
        )
        company_name = st.text_input(
            "Company Name *",
            placeholder="e.g., Acme Analytics",
        )

    with col2:
        manual_notes = st.text_area(
            "Analyst Notes (optional)",
            placeholder=(
                "Add anything you know: LinkedIn URL, recent round details, "
                "how you found them, referral source, etc. "
                "This supplements (not replaces) web research."
            ),
            height=120,
        )

    st.divider()
    run_button = st.button(
        "⚡ Run Lead Intelligence Pipeline",
        type="primary",
        disabled=(not founder_name or not company_name),
    )

    if run_button:
        if not os.getenv("ANTHROPIC_API_KEY"):
            st.error(
                "**ANTHROPIC_API_KEY not found.** "
                "Add it to your `.env` file and restart Streamlit."
            )
            st.stop()

        with st.spinner(
            f"Researching {founder_name} at {company_name}... "
            "This typically takes 15–30 seconds."
        ):
            try:
                lead = run_lead_agent(
                    company_name=company_name.strip(),
                    founder_name=founder_name.strip(),
                    manual_notes=manual_notes.strip(),
                )

                st.success(f"Pipeline complete. Lead scored **{lead.fit_score}/10**.")
                st.divider()

                # ── RESULTS LAYOUT ──────────────────────────────────────
                res_col1, res_col2 = st.columns([1, 2])

                with res_col1:
                    st.markdown("### Lead Profile")
                    st.markdown(
                        f"**Company:** {lead.company_name}  \n"
                        f"**Founder:** {lead.founder_name}  \n"
                        f"**Stage:** {lead.funding_stage}  \n"
                        f"**Industry:** {lead.industry}  \n"
                    )
                    st.markdown(
                        f"**ICP Fit Score:** {score_badge(lead.fit_score)}",
                        unsafe_allow_html=True,
                    )
                    st.caption(lead.fit_rationale)
                    st.divider()
                    st.markdown("**Problem they solve:**")
                    st.info(lead.problem_being_solved or "—")
                    st.markdown("**Recent trigger / hook:**")
                    st.info(lead.recent_news_or_trigger or "—")
                    st.markdown("**Identified doc gaps:**")
                    st.warning(lead.doc_gaps_identified or "—")

                with res_col2:
                    st.markdown("### Generated Outreach")

                    tab_email, tab_linkedin = st.tabs(["📧 Email", "💼 LinkedIn"])

                    with tab_email:
                        email_content = lead.email_draft
                        st.markdown(
                            f'<div class="outreach-box">{email_content}</div>',
                            unsafe_allow_html=True,
                        )
                        st.download_button(
                            "Download Email Draft",
                            data=email_content,
                            file_name=f"email_{lead.company_name.replace(' ', '_')}.txt",
                            mime="text/plain",
                        )

                    with tab_linkedin:
                        st.markdown(
                            f'<div class="linkedin-box">{lead.linkedin_draft}</div>',
                            unsafe_allow_html=True,
                        )
                        st.download_button(
                            "Download LinkedIn Draft",
                            data=lead.linkedin_draft,
                            file_name=f"linkedin_{lead.company_name.replace(' ', '_')}.txt",
                            mime="text/plain",
                        )

                # ── ACTION BUTTONS ──────────────────────────────────────
                st.divider()
                action_col1, action_col2, _ = st.columns([1, 1, 2])
                with action_col1:
                    if st.button("✅ Mark Outreach Sent", key="mark_sent"):
                        conn = get_db_connection()
                        # Get the most recent lead ID for this company
                        row = conn.execute(
                            "SELECT id FROM leads WHERE company_name = ? ORDER BY created_at DESC LIMIT 1",
                            (lead.company_name,)
                        ).fetchone()
                        if row:
                            mark_outreach_sent(conn, row["id"])
                        conn.close()
                        st.success("Marked as sent in pipeline.")

                with action_col2:
                    if st.button("🔄 Re-run This Lead", key="rerun"):
                        st.rerun()

            except ValueError as e:
                st.error(f"Agent returned malformed output: {e}")
            except Exception as e:
                st.error(f"Unexpected error: {e}")
                logger.exception("Lead pipeline failed")


# ---------------------------------------------------------------------------
# PAGE: LEAD PIPELINE
# ---------------------------------------------------------------------------
elif page == "Lead Pipeline":
    st.title("Lead Pipeline")
    st.caption("All researched leads, sorted by ICP fit score. Use this as your CRM.")
    st.divider()

    conn = get_db_connection()
    leads = fetch_all_leads(conn)
    conn.close()

    if not leads:
        st.info(
            "No leads yet. Go to **New Lead** to run your first research pipeline."
        )
        st.stop()

    # ── SUMMARY METRICS ─────────────────────────────────────────────────
    total = len(leads)
    high_fit = sum(1 for l in leads if l["fit_score"] >= 7)
    sent = sum(1 for l in leads if l["outreach_sent"])
    avg_score = sum(l["fit_score"] for l in leads) / total if total else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Leads", total)
    m2.metric("High Fit (7+)", high_fit)
    m3.metric("Outreach Sent", sent)
    m4.metric("Avg ICP Score", f"{avg_score:.1f}/10")

    st.divider()

    # ── FILTER CONTROLS ──────────────────────────────────────────────────
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        min_score = st.slider("Min Fit Score", 1, 10, 5)
    with filter_col2:
        stage_filter = st.multiselect(
            "Stage",
            options=["pre-seed", "seed", "series-a", "unknown"],
            default=["pre-seed", "seed"],
        )
    with filter_col3:
        sent_filter = st.selectbox(
            "Outreach Status",
            ["All", "Sent", "Not Sent"],
        )

    # Apply filters
    filtered = [
        l for l in leads
        if l["fit_score"] >= min_score
        and (not stage_filter or l["funding_stage"] in stage_filter)
        and (
            sent_filter == "All"
            or (sent_filter == "Sent" and l["outreach_sent"])
            or (sent_filter == "Not Sent" and not l["outreach_sent"])
        )
    ]

    st.caption(f"Showing {len(filtered)} of {total} leads")
    st.divider()

    # ── LEAD CARDS ───────────────────────────────────────────────────────
    for lead in filtered:
        with st.expander(
            f"{'✅' if lead['outreach_sent'] else '📋'} "
            f"{lead['company_name']} — {lead['founder_name']} | "
            f"Score: {lead['fit_score']}/10 | {lead['funding_stage']} | {lead['industry']}"
        ):
            lc1, lc2 = st.columns([1, 2])

            with lc1:
                st.markdown(
                    f"**Fit Score:** {score_badge(lead['fit_score'])}",
                    unsafe_allow_html=True,
                )
                st.caption(lead["fit_rationale"])
                st.markdown(f"**Doc Gaps:** {lead['doc_gaps_identified']}")
                st.markdown(f"**Trigger:** {lead['recent_news_or_trigger']}")
                st.caption(f"Added: {lead['created_at'][:10]}")

            with lc2:
                tab_e, tab_l = st.tabs(["Email", "LinkedIn"])
                with tab_e:
                    st.code(lead["email_draft"], language=None)
                with tab_l:
                    st.code(lead["linkedin_draft"], language=None)


# ---------------------------------------------------------------------------
# PAGE: SETTINGS
# ---------------------------------------------------------------------------
elif page == "Settings":
    st.title("Settings & Configuration")
    st.divider()

    st.markdown("### Environment Variables")
    st.caption(
        "These are loaded from your `.env` file. Never commit `.env` to version control."
    )

    env_data = {
        "Variable": ["ANTHROPIC_API_KEY", "TAVILY_API_KEY"],
        "Status": [
            "✅ Set" if os.getenv("ANTHROPIC_API_KEY") else "❌ Missing (required)",
            "✅ Set" if os.getenv("TAVILY_API_KEY") else "⚠️ Not set (optional — disables web research)",
        ],
        "Notes": [
            "Required for all LLM inference",
            "Enables automated web research on founders. Get key at tavily.com",
        ]
    }
    st.table(pd.DataFrame(env_data))

    st.divider()
    st.markdown("### Database")
    st.caption("SQLite database at `data/leads.db`. Export below for backup.")

    conn = get_db_connection()
    leads = fetch_all_leads(conn)
    conn.close()

    if leads:
        df = pd.DataFrame(leads)
        csv = df.to_csv(index=False)
        st.download_button(
            "⬇️ Export All Leads (CSV)",
            data=csv,
            file_name=f"fds_leads_{datetime.utcnow().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )
        st.caption(f"{len(leads)} leads in database")

    st.divider()
    st.markdown("### Ideal Client Profile (ICP) — Current Scoring Weights")
    icp_data = {
        "Criterion": [
            "Actively fundraising (pre-seed/seed)",
            "B2B SaaS / FinTech / data-driven",
            "Product in market, limited traction narrative",
            "Founded in last 24 months",
            "Technical founder, limited financial presentation exp.",
            "Venture-backable market (TAM > $1B)",
            "Series B or later (deduction)",
            "B2C consumer, no enterprise angle (deduction)",
        ],
        "Points": ["+3", "+2", "+2", "+1", "+1", "+1", "−2", "−2"],
    }
    st.table(pd.DataFrame(icp_data))
    st.caption("Modify `RESEARCH_SYNTHESIS_PROMPT` in `lead_agent.py` to adjust weights.")
