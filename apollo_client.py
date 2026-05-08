"""
apollo_client.py
Financial Document Studio — Apollo.io Research Layer

Replaces the Tavily web search layer with structured Apollo.io API calls.
Apollo returns verified, structured data (funding stage, LinkedIn URL, 
company headcount, industry) — lower hallucination risk than raw web text.

Apollo API Docs: https://apolloio.github.io/apollo-api-docs/
"""

import os
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

APOLLO_BASE_URL = "https://api.apollo.io/api/v1"


# ---------------------------------------------------------------------------
# CORE API WRAPPER
# ---------------------------------------------------------------------------

def _apollo_post(endpoint: str, payload: dict) -> dict:
    """
    Make an authenticated POST request to the Apollo API.
    Raises on HTTP errors; returns parsed JSON on success.
    """
    api_key = os.getenv("APOLLO_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "APOLLO_API_KEY not set. Add it to your .env file."
        )

    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "x-api-key": api_key,
    }

    response = requests.post(
        f"{APOLLO_BASE_URL}/{endpoint}",
        headers=headers,
        json=payload,
        timeout=15,
    )

    if response.status_code == 401:
        raise PermissionError(
            "Apollo API returned 401 Unauthorized. Check your APOLLO_API_KEY."
        )
    if response.status_code == 422:
        raise ValueError(
            f"Apollo API returned 422 — invalid request payload: {response.text}"
        )

    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# PERSON ENRICHMENT
# ---------------------------------------------------------------------------

def enrich_person(
    first_name: str,
    last_name: str,
    company_name: str,
    reveal_email: bool = False,
) -> dict:
    """
    Enrich a founder via Apollo's People Match endpoint.
    Returns structured contact + company data.

    Args:
        first_name:     Founder's first name
        last_name:      Founder's last name
        company_name:   Company they founded
        reveal_email:   If True, consumes an Apollo email credit to reveal
                        their direct email. Only enable if your plan has credits.

    Returns:
        Dict with keys: person, organization (see _parse_person_data)
    """
    payload = {
        "first_name": first_name,
        "last_name": last_name,
        "organization_name": company_name,
        "reveal_personal_emails": False,  # personal emails stay off
        "reveal_phone_number": False,
    }

    if reveal_email:
        payload["reveal_personal_emails"] = False  # keep off — use work email only
        # Apollo charges credits to reveal emails; we surface the flag but
        # default to off to avoid unintended credit burn.

    try:
        data = _apollo_post("people/match", payload)
        person = data.get("person")

        if not person:
            logger.warning(
                "Apollo people/match returned no person for %s %s at %s",
                first_name, last_name, company_name,
            )
            return {}

        return _parse_person_data(person)

    except Exception as e:
        logger.error("Apollo person enrichment failed: %s", str(e))
        return {}


# ---------------------------------------------------------------------------
# ORGANIZATION ENRICHMENT (standalone — useful for company-only lookups)
# ---------------------------------------------------------------------------

def enrich_organization(company_name: str, company_domain: Optional[str] = None) -> dict:
    """
    Enrich a company via Apollo's Mixed Companies Search.
    Returns structured org data: funding, headcount, industry, description.

    Useful as a fallback if person enrichment returns sparse org data.
    """
    payload = {
        "q_organization_name": company_name,
        "page": 1,
        "per_page": 1,
    }
    if company_domain:
        payload["q_organization_domains"] = [company_domain]

    try:
        data = _apollo_post("mixed_companies/search", payload)
        orgs = data.get("organizations", [])

        if not orgs:
            logger.warning("Apollo org search returned no results for %s", company_name)
            return {}

        return _parse_org_data(orgs[0])

    except Exception as e:
        logger.error("Apollo org enrichment failed: %s", str(e))
        return {}


# ---------------------------------------------------------------------------
# DATA PARSERS — normalize Apollo's response schema into clean dicts
# ---------------------------------------------------------------------------

def _parse_person_data(person: dict) -> dict:
    """
    Extract the fields relevant to FDS's ICP scoring from Apollo's
    person object. Nested org data is also extracted here.
    """
    org = person.get("organization") or {}

    # ── Person fields ────────────────────────────────────────────────────
    parsed_person = {
        "full_name": person.get("name", ""),
        "title": person.get("title", ""),
        "seniority": person.get("seniority", ""),        # e.g., "founder", "c_suite"
        "linkedin_url": person.get("linkedin_url", ""),
        "email": person.get("email", ""),                # populated if revealed
        "city": person.get("city", ""),
        "state": person.get("state", ""),
        "country": person.get("country", ""),
    }

    # ── Organization fields ──────────────────────────────────────────────
    parsed_org = _parse_org_data(org)

    return {
        "person": parsed_person,
        "organization": parsed_org,
    }


def _parse_org_data(org: dict) -> dict:
    """
    Normalize Apollo's organization object into FDS-relevant fields.
    Maps Apollo's raw funding_events list into a clean summary.
    """
    # Apollo stores funding events as a list of dicts with keys:
    # date, news_url, type (e.g. "Seed", "Series A"), amount, currency, investors
    funding_events = org.get("funding_events") or []
    latest_round = None
    total_raised_usd = 0

    for event in sorted(
        funding_events,
        key=lambda e: e.get("date") or "",
        reverse=True,
    ):
        if latest_round is None:
            latest_round = {
                "type": event.get("type", "unknown"),
                "date": event.get("date", ""),
                "amount_usd": event.get("amount") or 0,
                "investors": event.get("investors") or [],
                "news_url": event.get("news_url", ""),
            }
        amount = event.get("amount") or 0
        if isinstance(amount, (int, float)):
            total_raised_usd += amount

    # Apollo industries is a list like ["information technology", "saas"]
    industries = org.get("industries") or []
    keywords = org.get("keywords") or []

    return {
        "name": org.get("name", ""),
        "domain": org.get("primary_domain", ""),
        "website_url": org.get("website_url", ""),
        "short_description": org.get("short_description", ""),
        "industry": ", ".join(industries[:3]) if industries else "",
        "keywords": keywords[:10],
        "employee_count": org.get("estimated_num_employees") or 0,
        "employee_range": org.get("employees_range", ""),  # e.g. "1-10"
        "founded_year": org.get("founded_year"),
        "hq_city": org.get("city", ""),
        "hq_country": org.get("country", ""),
        "latest_funding_round": latest_round,
        "total_raised_usd": total_raised_usd,
        "funding_stage": _infer_funding_stage(latest_round, total_raised_usd),
        "linkedin_url": org.get("linkedin_url", ""),
    }


def _infer_funding_stage(latest_round: Optional[dict], total_raised: int) -> str:
    """
    Map Apollo's funding round type to FDS's ICP stage taxonomy.
    Apollo round types: "Pre Seed", "Seed", "Series A", "Series B", etc.
    """
    if not latest_round:
        # Fall back to total raised as a rough proxy
        if total_raised == 0:
            return "unknown"
        elif total_raised < 1_000_000:
            return "pre-seed"
        elif total_raised < 5_000_000:
            return "seed"
        elif total_raised < 20_000_000:
            return "series-a"
        else:
            return "series-b+"

    round_type = (latest_round.get("type") or "").lower()

    mapping = {
        "pre seed": "pre-seed",
        "pre-seed": "pre-seed",
        "angel": "pre-seed",
        "seed": "seed",
        "series a": "series-a",
        "series b": "series-b+",
        "series c": "series-b+",
        "growth": "series-b+",
        "venture": "seed",       # generic "Venture" rounds often map to seed
    }

    for key, stage in mapping.items():
        if key in round_type:
            return stage

    return "unknown"


# ---------------------------------------------------------------------------
# UNIFIED RESEARCH FUNCTION (drop-in replacement for Tavily's research_founder)
# ---------------------------------------------------------------------------

def research_founder_apollo(
    company_name: str,
    founder_name: str,
) -> dict:
    """
    Main entry point. Takes a founder name + company and returns a
    structured research dict ready for Claude's synthesis prompt.

    This replaces research_founder() from the Tavily implementation.
    Returns structured data (not raw text) — the synthesis prompt
    receives this as formatted JSON context, dramatically reducing
    the surface area for hallucination.

    Returns empty dict on failure (agent continues with manual notes).
    """
    name_parts = founder_name.strip().split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    logger.info(
        "Apollo lookup: %s %s @ %s", first_name, last_name, company_name
    )

    # Try person enrichment first (most complete data)
    result = enrich_person(first_name, last_name, company_name)

    # If person match returned sparse org data, supplement with org search
    if result and not result.get("organization", {}).get("short_description"):
        logger.info("Supplementing with Apollo org search for %s", company_name)
        org_supplement = enrich_organization(company_name)
        if org_supplement:
            # Merge — person enrichment takes precedence, fill gaps from org search
            for key, val in org_supplement.items():
                if not result["organization"].get(key):
                    result["organization"][key] = val

    return result


def format_apollo_context_for_llm(apollo_data: dict) -> str:
    """
    Serialize structured Apollo data into a clean, LLM-readable
    context string. Deliberately formatted (not raw JSON) to guide
    the model toward relevant fields and suppress irrelevant noise.
    """
    if not apollo_data:
        return ""

    person = apollo_data.get("person", {})
    org = apollo_data.get("organization", {})
    funding = org.get("latest_funding_round") or {}

    lines = [
        "=== APOLLO.IO VERIFIED DATA ===",
        "",
        "PERSON:",
        f"  Name:       {person.get('full_name', 'unknown')}",
        f"  Title:      {person.get('title', 'unknown')}",
        f"  Seniority:  {person.get('seniority', 'unknown')}",
        f"  LinkedIn:   {person.get('linkedin_url', 'not found')}",
        f"  Email:      {person.get('email', 'not revealed')}",
        f"  Location:   {person.get('city', '')}, {person.get('state', '')}, {person.get('country', '')}",
        "",
        "COMPANY:",
        f"  Name:       {org.get('name', 'unknown')}",
        f"  Domain:     {org.get('domain', '')}",
        f"  Industry:   {org.get('industry', 'unknown')}",
        f"  Employees:  {org.get('employee_range', '')} (~{org.get('employee_count', 'unknown')})",
        f"  Founded:    {org.get('founded_year', 'unknown')}",
        f"  HQ:         {org.get('hq_city', '')}, {org.get('hq_country', '')}",
        f"  Description:{org.get('short_description', 'none available')}",
        f"  Keywords:   {', '.join(org.get('keywords', []))}",
        "",
        "FUNDING:",
        f"  Stage:      {org.get('funding_stage', 'unknown')}",
        f"  Total Raised: ${org.get('total_raised_usd', 0):,.0f}",
    ]

    if funding:
        investors = funding.get("investors") or []
        investor_str = (
            ", ".join(str(i.get("name", i)) if isinstance(i, dict) else str(i)
                      for i in investors[:5])
            or "not disclosed"
        )
        lines += [
            f"  Latest Round: {funding.get('type', 'unknown')} "
            f"(${funding.get('amount_usd', 0):,.0f}) on {funding.get('date', 'unknown')}",
            f"  Investors:    {investor_str}",
            f"  News URL:     {funding.get('news_url', '')}",
        ]
    else:
        lines.append("  Latest Round: none on record")

    lines.append("")
    lines.append("=== END APOLLO DATA ===")

    return "\n".join(lines)
