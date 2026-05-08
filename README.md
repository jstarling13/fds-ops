# Financial Document Studio — Lead Intelligence Agent

Internal tool for researching seed-stage founders, scoring ICP fit, and generating personalized outreach. Built on Apollo.io + Anthropic Claude + Streamlit.

---

## What It Does

1. **Apollo Lookup** — pulls verified funding stage, employee count, LinkedIn URL, industry, and company description for any founder + company pair
2. **ICP Scoring** — Claude scores each lead 1–10 against FDS's ideal client profile using structured Apollo data (not web text)
3. **Outreach Generation** — produces a personalized email and LinkedIn message grounded in the lead's specific situation
4. **Pipeline Tracking** — persists every lead to SQLite with outreach status, exportable as CSV

---

## Project Structure

```
fds-lead-agent/
├── app.py                  # Streamlit frontend (run this)
├── lead_agent.py           # Core pipeline: research → score → outreach → persist
├── apollo_client.py        # Apollo.io API wrapper and data parsers
├── requirements.txt        # Python dependencies
├── .env.template           # Copy to .env and fill in keys
├── .streamlit/
│   └── config.toml         # Streamlit theme and server config
├── data/                   # Auto-created on first run
│   └── leads.db            # SQLite database (gitignored)
└── logs/                   # Auto-created on first run (gitignored)
```

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/fds-lead-agent.git
cd fds-lead-agent
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.template .env
```

Open `.env` and fill in:

```
ANTHROPIC_API_KEY=your_key_here   # console.anthropic.com
APOLLO_API_KEY=your_key_here      # apollo.io → Settings → Integrations → API
```

### 3. Run

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`

---

## API Keys

| Key | Where to get it | Required? |
|-----|----------------|-----------|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | Yes |
| `APOLLO_API_KEY` | Apollo.io → Settings → Integrations → API | Yes |

---

## ICP Scoring Criteria

| Criterion | Points |
|-----------|--------|
| Funding stage is pre-seed or seed | +3 |
| Industry is B2B SaaS, FinTech, data/analytics | +2 |
| Employee count 1–25 | +2 |
| Founded within last 3 years | +1 |
| Founder title is CEO/Founder/Co-Founder | +1 |
| Total raised under $3M | +1 |
| Series B or later | −2 |
| Employee count over 100 | −2 |
| No funding data and no description | −1 |

Adjust weights in `RESEARCH_SYNTHESIS_PROMPT` inside `lead_agent.py`.

---

## Deployment (Streamlit Community Cloud)

1. Push this repo to GitHub (make sure `.env` is gitignored)
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your repo, set `app.py` as the entry point
4. Add your API keys under **Settings → Secrets** in the Streamlit dashboard

---

## Next Agents (Roadmap)

- [ ] **Revenue Pulse Dashboard** — Monte Carlo cash flow forecasting on project pipeline data
- [ ] **Document Production Orchestrator** — founder intake → first-draft pitch deck/memo routing
- [ ] **QC Agent** — RAG-based review layer checking AI drafts against FDS's quality rubric

---

## Notes

- `data/leads.db` is gitignored — back it up separately or migrate to Supabase for prod
- Apollo's `people/match` endpoint does not burn email reveal credits by default. Enable in `apollo_client.py` → `enrich_person()` if needed
- All LLM calls use `claude-sonnet-4-20250514`. Do not swap to a smaller model for financial outreach — determinism matters
