"""
server.py
Financial Document Studio — FastAPI Backend
Replaces Streamlit. Serves the HTML frontend and exposes REST endpoints.

Run: python server.py
Then open: http://localhost:8001
"""

import os
import csv
import logging
import sqlite3
from io import StringIO
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from lead_agent import run_lead_agent, init_db, fetch_all_leads, mark_outreach_sent

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="FDS Lead Intelligence", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# REQUEST MODELS
# ---------------------------------------------------------------------------

class LeadRequest(BaseModel):
    founder_name: str
    company_name: str
    manual_notes: str = ""


class NoteUpdate(BaseModel):
    notes: str


# ---------------------------------------------------------------------------
# SERVE FRONTEND
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ---------------------------------------------------------------------------
# API ROUTES
# ---------------------------------------------------------------------------

@app.post("/api/research")
async def research_lead(req: LeadRequest):
    """Run the full lead intelligence pipeline."""
    if not req.founder_name.strip() or not req.company_name.strip():
        raise HTTPException(status_code=400, detail="founder_name and company_name are required.")

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured.")

    try:
        lead = run_lead_agent(
            company_name=req.company_name.strip(),
            founder_name=req.founder_name.strip(),
            manual_notes=req.manual_notes.strip(),
        )
        return {
            "company_name": lead.company_name,
            "founder_name": lead.founder_name,
            "funding_stage": lead.funding_stage,
            "industry": lead.industry,
            "problem_being_solved": lead.problem_being_solved,
            "recent_news_or_trigger": lead.recent_news_or_trigger,
            "doc_gaps_identified": lead.doc_gaps_identified,
            "fit_score": lead.fit_score,
            "fit_rationale": lead.fit_rationale,
            "email_draft": lead.email_draft,
            "linkedin_draft": lead.linkedin_draft,
            "linkedin_url": lead.linkedin_url,
            "email_address": lead.email_address,
            "created_at": lead.created_at,
        }
    except Exception as e:
        logger.exception("Lead pipeline error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/leads")
async def get_leads(min_score: int = 0, stage: str = "", sent: str = "all"):
    """Return all leads with optional filtering."""
    conn = init_db()
    leads = fetch_all_leads(conn)
    conn.close()

    if min_score:
        leads = [l for l in leads if l["fit_score"] >= min_score]
    if stage:
        leads = [l for l in leads if l["funding_stage"] == stage]
    if sent == "sent":
        leads = [l for l in leads if l["outreach_sent"]]
    elif sent == "pending":
        leads = [l for l in leads if not l["outreach_sent"]]

    return {"leads": leads, "total": len(leads)}


@app.patch("/api/leads/{lead_id}/sent")
async def mark_sent(lead_id: int):
    conn = init_db()
    mark_outreach_sent(conn, lead_id)
    conn.close()
    return {"ok": True}


@app.patch("/api/leads/{lead_id}/notes")
async def update_notes(lead_id: int, body: NoteUpdate):
    conn = init_db()
    conn.execute("UPDATE leads SET notes = ? WHERE id = ?", (body.notes, lead_id))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/leads/{lead_id}")
async def delete_lead(lead_id: int):
    conn = init_db()
    conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/export")
async def export_csv():
    """Export all leads as CSV download."""
    conn = init_db()
    leads = fetch_all_leads(conn)
    conn.close()

    output = StringIO()
    if leads:
        writer = csv.DictWriter(output, fieldnames=leads[0].keys())
        writer.writeheader()
        writer.writerows(leads)

    output.seek(0)
    filename = f"fds_leads_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/status")
async def status():
    return {
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
        "apollo": bool(os.getenv("APOLLO_API_KEY")),
    }


# ---------------------------------------------------------------------------
# ENTRYPOINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8001, reload=True)
