"""
lead_agent.py
Financial Document Studio — Lead Intelligence Agent (Core Logic)
Principal Engineer: AI Systems Architect

Responsibilities:
  - Research a target founder/company using Apollo.io (verified structured data)
  - Score lead fit against FDS's ideal client profile (ICP)
  - Generate personalized, non-generic outreach (email + LinkedIn)
  - Persist all leads and outputs to SQLite for pipeline tracking

Dependencies: anthropic, requests, sqlite3 (stdlib)
"""

import os
import json
import sqlite3
import logging
from datetime import datetime
from dataclasses import dataclass, asdict

import anthropic
from apollo_client import (
    research_founder_apollo,
    format_apollo_context_for_llm,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DATA MODELS
# ---------------------------------------------------------------------------

@dataclass
class LeadProfile:
    """Structured representation of a researched lead."""
    company_name: str
    founder_name: str
    funding_stage: str                   # pre-seed / seed / series-a / series-b+
    industry: str
    problem_being_solved: str
    recent_news_or_trigger: str          # the hook — recent raise, launch, etc.
    doc_gaps_identified: str             # what they likely need from FDS
    fit_score: int                       # 1–10 ICP alignment score
    fit_rationale: str
    email_draft: str
    linkedin_draft: str
    linkedin_url: str                    # from Apollo — direct link for outreach
    email_address: str                   # from Apollo — if revealed
    raw_research: str                    # Apollo formatted context, stored for RAG
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()


# ---------------------------------------------------------------------------
# SYSTEM PROMPTS  (deterministic, hallucination-minimized)
# ---------------------------------------------------------------------------

# Apollo provides structured, verified data — the model is constrained to
# only use what Apollo returns. No inference from ambiguous web text.
RESEARCH_SYNTHESIS_PROMPT = """You are a senior business analyst at Financial Document Studio (FDS), 
a boutique advisory firm that produces institutional-grade financial materials for pre-seed and 
seed-stage founders. Your materials include: pitch decks, investment memos, one-pagers, CIMs, 
financial models, and M&A packages.

Your task: Analyze the provided Apollo.io verified data about a target founder/company and extract 
ONLY facts explicitly present in the data. Do not infer, fabricate, or assume details not present.
If a field says "unknown" or "none available," reflect that honestly — do not guess.

Return a JSON object with EXACTLY these keys:
{
  "funding_stage": "<use the Apollo funding_stage field verbatim if present; otherwise 'unknown'>",
  "industry": "<use Apollo industry field; max 4 words>",
  "problem_being_solved": "<derived from Apollo short_description only; 1 sentence max; 'unknown' if absent>",
  "recent_news_or_trigger": "<the most actionable recent event from Apollo data: funding round with date, or 'none on record'>",
  "doc_gaps_identified": "<which FDS deliverables this founder most likely needs based on their stage and profile>",
  "fit_score": <integer 1-10 based on ICP match criteria below>,
  "fit_rationale": "<2 sentences citing specific Apollo data points that drove the score>"
}

ICP SCORING CRITERIA (apply to calculate fit_score):
- +3 pts: Funding stage is pre-seed or seed
- +2 pts: Industry is B2B SaaS, FinTech, data/analytics, or enterprise software
- +2 pts: Employee count is 1–25 (early stage, resource-constrained)
- +1 pt: Founded within last 3 years
- +1 pt: Founder title contains "CEO", "Founder", or "Co-Founder" (decision-maker)
- +1 pt: Total raised is under $3M (likely still needs external financial materials)
- Deduct 2 pts: Series B or later (outgrown FDS's core offering)
- Deduct 2 pts: Employee count over 100 (likely has in-house finance team)
- Deduct 1 pt: No funding data on record AND no description (too cold to qualify)

Return ONLY the JSON object. No preamble, no markdown fences."""


OUTREACH_GENERATION_PROMPT = """You are writing outreach for Jacob, founder of Financial Document Studio (FDS).

ABOUT FDS:
Financial Document Studio produces institutional-grade financial materials for pre-seed and 
seed-stage founders: pitch decks, investment memos, financial models, CIMs, and M&A packages. 
Our work is used to raise capital from institutional LPs, angels, and seed funds.

JACOB'S VOICE: Direct, peer-level (not salesy), concise, references specific details about the 
founder's company. Never uses "I hope this email finds you well" or any generic openers. 
Leads with their world, not FDS's pitch. One ask per message. Contractions over formal phrasing.
Does not say "I came across your profile" or "I noticed" — sounds robotic.
Does reference specific data points: funding round, company description, employee count.

TASK: Generate two outreach variants based on the lead profile below.

1. EMAIL (subject line + body, max 120 words in body)
   - Subject: specific, not clickbait, references their company or round
   - Body: open with their situation → identify a specific doc gap → one concrete value prop → CTA is a 15-min call

2. LINKEDIN MESSAGE (max 60 words)
   - Even more direct. No subject line. Peer-to-peer tone. One idea.

Return ONLY a JSON object:
{
  "email_subject": "...",
  "email_body": "...",
  "linkedin_message": "..."
}

No preamble, no markdown fences."""


# ---------------------------------------------------------------------------
# DATABASE LAYER
# ---------------------------------------------------------------------------

def init_db(db_path: str = "data/leads.db") -> sqlite3.Connection:
    """Initialize SQLite database. Idempotent — safe to call on every startup."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name            TEXT NOT NULL,
            founder_name            TEXT NOT NULL,
            funding_stage           TEXT,
            industry                TEXT,
            problem_being_solved    TEXT,
            recent_news_or_trigger  TEXT,
            doc_gaps_identified     TEXT,
            fit_score               INTEGER,
            fit_rationale           TEXT,
            email_draft             TEXT,
            linkedin_draft          TEXT,
            linkedin_url            TEXT,
            email_address           TEXT,
            raw_research            TEXT,
            created_at              TEXT,
            outreach_sent           INTEGER DEFAULT 0,
            notes                   TEXT
        )
    """)
    conn.commit()
    return conn


def save_lead(conn: sqlite3.Connection, lead: LeadProfile) -> int:
    """Persist a LeadProfile to SQLite. Returns the new row ID."""
    data = asdict(lead)
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?" for _ in data])
    cursor = conn.execute(
        f"INSERT INTO leads ({cols}) VALUES ({placeholders})",
        list(data.values())
    )
    conn.commit()
    logger.info("Lead saved — ID: %d | %s | Score: %d",
                cursor.lastrowid, lead.company_name, lead.fit_score)
    return cursor.lastrowid


def fetch_all_leads(conn: sqlite3.Connection) -> list[dict]:
    """Return all leads sorted by fit_score descending."""
    rows = conn.execute(
        "SELECT * FROM leads ORDER BY fit_score DESC, created_at DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def mark_outreach_sent(conn: sqlite3.Connection, lead_id: int) -> None:
    conn.execute("UPDATE leads SET outreach_sent = 1 WHERE id = ?", (lead_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# RESEARCH LAYER (Apollo.io)
# ---------------------------------------------------------------------------

def research_founder(
    company_name: str,
    founder_name: str,
) -> tuple[str, dict]:
    """
    Query Apollo.io for structured founder + company data.

    Returns:
        (context_str, apollo_data)
        context_str: Formatted string for LLM ingestion
        apollo_data: Raw dict for direct field extraction (LinkedIn URL, email, etc.)

    Falls back gracefully if APOLLO_API_KEY is not set — agent continues
    with manual notes only.
    """
    if not os.getenv("APOLLO_API_KEY"):
        logger.warning("APOLLO_API_KEY not set — skipping Apollo research.")
        return "", {}

    try:
        apollo_data = research_founder_apollo(company_name, founder_name)
        context_str = format_apollo_context_for_llm(apollo_data)
        stage = apollo_data.get("organization", {}).get("funding_stage", "unknown")
        logger.info("Apollo data retrieved for %s — stage: %s", company_name, stage)
        return context_str, apollo_data

    except Exception as e:
        logger.error("Apollo research failed: %s", str(e))
        return "", {}


# ---------------------------------------------------------------------------
# CORE AGENT LOGIC
# ---------------------------------------------------------------------------

def synthesize_lead_profile(
    client: anthropic.Anthropic,
    company_name: str,
    founder_name: str,
    research_context: str,
    manual_notes: str = "",
) -> dict:
    """
    Pass Apollo context to Claude. Extract structured lead profile as JSON.
    """
    full_context = research_context
    if manual_notes:
        full_context += f"\n\nANALYST NOTES (manually provided):\n{manual_notes}"

    if not full_context.strip():
        full_context = (
            f"No Apollo data available. Company: {company_name}. "
            f"Founder: {founder_name}. Score conservatively."
        )

    user_message = (
        f"APOLLO DATA:\n\n{full_context}\n\n"
        f"TARGET COMPANY: {company_name}\n"
        f"TARGET FOUNDER: {founder_name}\n\n"
        "Analyze and return the JSON profile."
    )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=RESEARCH_SYNTHESIS_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned malformed JSON during synthesis: {raw}") from e


def generate_outreach(
    client: anthropic.Anthropic,
    profile_data: dict,
    company_name: str,
    founder_name: str,
) -> dict:
    """Generate personalized email + LinkedIn outreach from the lead profile."""
    profile_summary = (
        f"Company: {company_name}\n"
        f"Founder: {founder_name}\n"
        f"Stage: {profile_data.get('funding_stage', 'unknown')}\n"
        f"Industry: {profile_data.get('industry', 'unknown')}\n"
        f"Problem they solve: {profile_data.get('problem_being_solved', '')}\n"
        f"Recent trigger/news: {profile_data.get('recent_news_or_trigger', '')}\n"
        f"Document gaps: {profile_data.get('doc_gaps_identified', '')}\n"
        f"Fit rationale: {profile_data.get('fit_rationale', '')}\n"
    )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=OUTREACH_GENERATION_PROMPT,
        messages=[{
            "role": "user",
            "content": f"LEAD PROFILE:\n\n{profile_summary}\n\nGenerate the outreach."
        }],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError("Claude returned malformed JSON during outreach generation.") from e


# ---------------------------------------------------------------------------
# MAIN PIPELINE
# ---------------------------------------------------------------------------

def run_lead_agent(
    company_name: str,
    founder_name: str,
    manual_notes: str = "",
    db_path: str = "data/leads.db",
) -> LeadProfile:
    """
    Full pipeline: Apollo research → synthesize → score → outreach → persist.

    Args:
        company_name:   Target company (e.g., "Acme Analytics")
        founder_name:   Founder's full name (e.g., "Sarah Chen")
        manual_notes:   Optional analyst context — supplements Apollo data
        db_path:        SQLite path

    Returns:
        LeadProfile with all fields populated and persisted.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set. Add it to your .env file.")

    client = anthropic.Anthropic(api_key=api_key)
    conn = init_db(db_path)

    logger.info("Pipeline starting: %s / %s", company_name, founder_name)

    # Step 1: Apollo research
    logger.info("Step 1/4 — Apollo.io lookup...")
    research_context, apollo_data = research_founder(company_name, founder_name)

    # Step 2: Synthesize + score via Claude
    logger.info("Step 2/4 — Synthesizing lead profile...")
    profile_data = synthesize_lead_profile(
        client, company_name, founder_name, research_context, manual_notes
    )

    # Step 3: Generate outreach
    logger.info("Step 3/4 — Generating outreach...")
    outreach_data = generate_outreach(client, profile_data, company_name, founder_name)

    # Step 4: Extract Apollo direct-contact fields
    person = apollo_data.get("person", {})
    org = apollo_data.get("organization", {})

    # Step 5: Assemble and persist
    logger.info("Step 4/4 — Persisting to database...")
    lead = LeadProfile(
        company_name=company_name,
        founder_name=founder_name,
        funding_stage=profile_data.get("funding_stage", "unknown"),
        industry=profile_data.get("industry", "unknown"),
        problem_being_solved=profile_data.get("problem_being_solved", ""),
        recent_news_or_trigger=profile_data.get("recent_news_or_trigger", ""),
        doc_gaps_identified=profile_data.get("doc_gaps_identified", ""),
        fit_score=int(profile_data.get("fit_score", 0)),
        fit_rationale=profile_data.get("fit_rationale", ""),
        email_draft=(
            f"Subject: {outreach_data.get('email_subject', '')}\n\n"
            f"{outreach_data.get('email_body', '')}"
        ),
        linkedin_draft=outreach_data.get("linkedin_message", ""),
        linkedin_url=person.get("linkedin_url", "") or org.get("linkedin_url", ""),
        email_address=person.get("email", ""),
        raw_research=research_context[:4000],
    )

    save_lead(conn, lead)
    conn.close()

    logger.info("Pipeline complete — %s scored %d/10", company_name, lead.fit_score)
    return lead
