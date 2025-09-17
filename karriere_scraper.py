# karriere_scraper.py
import os, re, time
from typing import List, Dict, Optional
from datetime import datetime
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

DEFAULT_TIMEOUT = int(os.getenv("SEL_TIMEOUT_SEC", "20"))
BASE_URL = "https://www.karriere.at/jobs"

def _build_driver() -> webdriver.Chrome:
    opts = Options()
    chrome_args = os.getenv(
        "SELENIUM_CHROME_ARGS",
        "--headless=new --no-sandbox --disable-dev-shm-usage --window-size=1366,768"
    ).split()
    for a in chrome_args:
        if a.strip():
            opts.add_argument(a.strip())
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(DEFAULT_TIMEOUT)
    return driver

def _wait_css(driver, css, timeout=None):
    WebDriverWait(driver, timeout or DEFAULT_TIMEOUT).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, css))
    )

def _visible_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def _accept_cookies_if_present(driver):
    # Try common consent buttons on karriere.at / OneTrust variants
    try:
        # OneTrust default id
        btn = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "#onetrust-accept-btn-handler"))
        )
        btn.click()
        time.sleep(0.3)
        return
    except Exception:
        pass
    # Text-based fallbacks (German/English)
    for text in ["Akzeptieren", "Zustimmen", "Alle akzeptieren", "Accept", "I agree"]:
        try:
            btn = WebDriverWait(driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, f"//button[contains(., '{text}')]"))
            )
            btn.click()
            time.sleep(0.3)
            return
        except Exception:
            continue

def _search_url(field: str, region: str, page: int = 1) -> str:
    # Simple & robust approach; adjust if site expects slugs
    path_field = quote(field)
    path_region = quote(region)
    url = f"{BASE_URL}/{path_field}/{path_region}"
    if page > 1:
        url += f"?page={page}"
    return url

def _collect_job_links_on_page(driver) -> List[str]:
    import re
    anchors = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/jobs/"]')
    links, seen = [], set()
    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue
        # keep only canonical detail pages like .../jobs/7605540
        if re.search(r"/jobs/\d+(?:[/?#].*)?$", href) and href not in seen:
            seen.add(href)
            links.append(href)
    return links


def _extract_job(driver, url: str) -> Optional[Dict]:
    import json, re
    from html import unescape
    try:
        driver.get(url)
        _wait_css(driver, "body")

        # --- Prefer JSON-LD (JobPosting) ---
        org = title = location = description = posted_at = None

        scripts = driver.find_elements(By.CSS_SELECTOR, 'script[type="application/ld+json"]')
        for s in scripts:
            try:
                raw = s.get_attribute("textContent") or s.get_attribute("innerHTML") or ""
                raw = raw.strip()
                if not raw:
                    continue
                data = json.loads(raw)
                # JSON-LD can be dict or list; normalize to list
                candidates = data if isinstance(data, list) else [data]
                for item in candidates:
                    if not isinstance(item, dict):
                        continue
                    # Some pages wrap JobPosting in @graph
                    graph = item.get("@graph") if "@graph" in item else None
                    if isinstance(graph, list):
                        for g in graph:
                            if isinstance(g, dict) and g.get("@type") == "JobPosting":
                                item = g
                                break
                    if item.get("@type") == "JobPosting":
                        title = item.get("title") or title
                        posted_at = item.get("datePosted") or posted_at
                        # Company
                        org_obj = item.get("hiringOrganization") or {}
                        if isinstance(org_obj, dict):
                            org = org_obj.get("name") or org
                        # Location
                        loc_obj = item.get("jobLocation") or {}
                        # jobLocation can be list or dict
                        if isinstance(loc_obj, list) and loc_obj:
                            loc_obj = loc_obj[0]
                        if isinstance(loc_obj, dict):
                            addr = loc_obj.get("address") or {}
                            if isinstance(addr, dict):
                                location = addr.get("addressLocality") or addr.get("addressRegion") or location
                        # Description (strip HTML tags crudely)
                        desc_html = item.get("description") or ""
                        if desc_html:
                            description = _visible_text(re.sub(r"<[^>]+>", " ", unescape(desc_html)))
                        break
            except Exception:
                continue

        # --- Fallbacks via CSS if JSON-LD missing/partial ---
        if not title:
            els = driver.find_elements(By.CSS_SELECTOR, 'h1,[data-qa="job-title"], h1[class*="title"]')
            if els: title = _visible_text(els[0].text)

        if not org:
            els = driver.find_elements(By.CSS_SELECTOR, '[data-qa="company-name"], a[href*="/firmen/"], .job-company, [itemprop="hiringOrganization"]')
            if els: org = _visible_text(els[0].text)

        if not location:
            els = driver.find_elements(By.CSS_SELECTOR, '[data-qa="job-location"], .job-location, [itemprop="addressLocality"], [data-qa="locations"]')
            if els: location = _visible_text(els[0].text)

        if not description:
            els = driver.find_elements(By.CSS_SELECTOR, '[data-qa="job-description"], article, .job-description, [itemprop="description"]')
            if els: description = _visible_text(els[0].text)

        if not posted_at:
            els = driver.find_elements(By.CSS_SELECTOR, 'time[datetime], [data-qa="job-posted"], .posted-date')
            if els:
                posted_at = (els[0].get_attribute("datetime") or els[0].text or "").strip()

        return {
            "title": title,
            "company": org,
            "location": location,
            "posted_at": posted_at,
            "link": url,
            "description": description
        }
    except TimeoutException:
        return None


def scrape_karriere(field: str, region: str, page_limit: int = 3, max_jobs: Optional[int] = None) -> Dict:
    """
    Crawl up to page_limit result pages for (field, region) and return structured jobs.
    """
    driver = _build_driver()
    jobs: List[Dict] = []
    try:
        driver.get(_search_url(field, region, page=1))
        _accept_cookies_if_present(driver)
        _wait_css(driver, "body")

        page = 1
        while page <= page_limit:
            if page > 1:
                driver.get(_search_url(field, region, page=page))
                _wait_css(driver, "body")

            links = _collect_job_links_on_page(driver)
            for link in links:
                job = _extract_job(driver, link)
                if job:
                    jobs.append(job)
                    if max_jobs and len(jobs) >= max_jobs:
                        break
            if max_jobs and len(jobs) >= max_jobs:
                break
            page += 1

        return {
            "field": field,
            "region": region,
            "count": len(jobs),
            "jobs": jobs,
            "meta": {"ts": int(datetime.utcnow().timestamp())}
        }
    finally:
        try:
            driver.quit()
        except Exception:
            pass
