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
    try:
        driver.get(url)
        _wait_css(driver, "body")
        title = None
        company = None
        location = None
        description = None
        posted_at = None

        els = driver.find_elements(By.CSS_SELECTOR, 'h1,[data-qa="job-title"]')
        if els: title = _visible_text(els[0].text)

        els = driver.find_elements(By.CSS_SELECTOR, '[data-qa="company-name"], a[href*="/firmen/"], .job-company')
        if els: company = _visible_text(els[0].text)

        els = driver.find_elements(By.CSS_SELECTOR, '[data-qa="job-location"], .job-location, [itemprop="addressLocality"]')
        if els: location = _visible_text(els[0].text)

        els = driver.find_elements(By.CSS_SELECTOR, '[data-qa="job-description"], article, .job-description')
        if els: description = _visible_text(els[0].text)

        els = driver.find_elements(By.CSS_SELECTOR, 'time[datetime], [data-qa="job-posted"], .posted-date')
        if els:
            posted_at = (els[0].get_attribute("datetime") or els[0].text or "").strip()

        return {
            "title": title,
            "company": company,
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
