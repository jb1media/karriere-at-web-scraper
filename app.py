# app.py
import os
from fastapi import FastAPI, HTTPException, Query, Header
from pydantic import BaseModel
from karriere_scraper import scrape_karriere

API_TOKEN = os.getenv("API_TOKEN", "")
DEFAULT_PAGE_LIMIT = int(os.getenv("PAGE_LIMIT_DEFAULT", "3"))

app = FastAPI(title="Karriere.at Scraper API", version="1.0.0")

class JobsResponse(BaseModel):
    field: str
    region: str
    count: int
    jobs: list
    meta: dict

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/karriere/search", response_model=JobsResponse)
def karriere_search(
    field: str = Query(..., description="e.g., 'IT, EDV'"),
    region: str = Query(..., description="e.g., 'Wien'"),
    page_limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=50),
    max_jobs: int | None = Query(None, ge=1, le=2000),
    token: str | None = Header(None, convert_underscores=False)
):
    if API_TOKEN and token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        return scrape_karriere(field=field, region=region, page_limit=page_limit, max_jobs=max_jobs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
from urllib.parse import unquote
@app.get("/url={raw}")
def proxy_style(raw: str, token: str | None = Header(None, convert_underscores=False)):
    if API_TOKEN and token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    decoded = unquote(raw)
    # You can parse "decoded" however you want; here we just echo it
    return {"hint": "Prefer /karriere/search with query params.", "raw": decoded}
