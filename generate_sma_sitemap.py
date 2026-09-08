#!/usr/bin/env python3
"""
NASA Safety and Mission Assurance (SMA) Policies Sitemap & URL Generator
Crawls https://sma.nasa.gov/policies/all-policies and aggregates all OSMA governance
documents: NASA Policy Directives (NPDs), NASA Procedural Requirements (NPRs),
NASA Standards, and NASA Handbooks / Guidance.

Where policies link to NTRS (NASA Technical Reports Server), this crawler queries
the official NTRS REST API to link directly to the approved full-text master PDF,
rather than stopping at the citation landing page.
"""

import concurrent.futures
from datetime import datetime, timezone
import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import requests

BASE_URL = "https://sma.nasa.gov"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
}

SMA_HUB_PAGES = [
    "https://sma.nasa.gov/policies",
    "https://sma.nasa.gov/policies/all-policies",
    "https://sma.nasa.gov/policies/policy-status",
    "https://sma.nasa.gov/sma-disciplines",
    "https://sma.nasa.gov/sma-disciplines/aviation-safety",
    "https://sma.nasa.gov/sma-disciplines/eee-parts",
    "https://sma.nasa.gov/sma-disciplines/electrical-safety",
    "https://sma.nasa.gov/sma-disciplines/elv-payload-safety",
    "https://sma.nasa.gov/sma-disciplines/facility-system-safety",
    "https://sma.nasa.gov/sma-disciplines/fire-protection",
    "https://sma.nasa.gov/sma-disciplines/gidep",
    "https://sma.nasa.gov/sma-disciplines/human-factors",
    "https://sma.nasa.gov/sma-disciplines/human-rating",
    "https://sma.nasa.gov/sma-disciplines/institutional-safety",
    "https://sma.nasa.gov/sma-disciplines/lifting-devices-and-equipment",
    "https://sma.nasa.gov/sma-disciplines/meteoroid-environments",
    "https://sma.nasa.gov/sma-disciplines/metrology-and-calibration",
    "https://sma.nasa.gov/sma-disciplines/mishap-investigation",
    "https://sma.nasa.gov/sma-disciplines/nondestructive-evaluation",
    "https://sma.nasa.gov/sma-disciplines/nsrs",
    "https://sma.nasa.gov/sma-disciplines/nuclear-flight-safety",
    "https://sma.nasa.gov/sma-disciplines/orbital-debris",
    "https://sma.nasa.gov/sma-disciplines/planetary-protection",
    "https://sma.nasa.gov/sma-disciplines/pressure-vessels-and-systems",
    "https://sma.nasa.gov/sma-disciplines/pyrotechnics-and-explosives-safety",
    "https://sma.nasa.gov/sma-disciplines/quality",
    "https://sma.nasa.gov/sma-disciplines/range-flight-safety",
    "https://sma.nasa.gov/sma-disciplines/reliability-and-maintainability",
    "https://sma.nasa.gov/sma-disciplines/risk-management",
    "https://sma.nasa.gov/sma-disciplines/safety-culture",
    "https://sma.nasa.gov/sma-disciplines/software-assurance-and-software-safety",
    "https://sma.nasa.gov/sma-disciplines/supply-chain-risk-management",
    "https://sma.nasa.gov/sma-disciplines/system-safety",
    "https://sma.nasa.gov/sma-disciplines/workmanship",
]

MINIMUM_EXPECTED_URLS = 75
MAX_RETRIES = 3
BACKOFF_BASE = 2


def fetch_with_retry(session: requests.Session, url: str, method: str = "GET") -> requests.Response | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if method.upper() == "HEAD":
                resp = session.head(url, headers=HEADERS, timeout=12, allow_redirects=True)
            else:
                resp = session.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
            if resp.status_code == 200:
                return resp
            if resp.status_code in [401, 403, 404]:
                return resp
        except Exception:
            pass
        if attempt < MAX_RETRIES:
            time.sleep(BACKOFF_BASE ** attempt)
    return None


def resolve_ntrs_pdf(session: requests.Session, link: str) -> str | None:
    """Extract citation ID from NTRS link and resolve the direct PDF download URL via official API."""
    m = re.search(r'(?:citations/|R=|casi\.ntrs\.nasa\.gov/)(\d{7,11})', link)
    if not m:
        return None
    cid = m.group(1)
    api_url = f"https://ntrs.nasa.gov/api/citations/{cid}"
    resp = fetch_with_retry(session, api_url)
    if not resp or resp.status_code != 200:
        return None
    try:
        data = resp.json()
        downloads = data.get("downloads", [])
        for d in downloads:
            if d.get("mimetype") == "application/pdf" or d.get("name", "").endswith(".pdf"):
                rel_link = d.get("links", {}).get("pdf") or d.get("links", {}).get("original")
                if rel_link:
                    pdf_url = f"https://ntrs.nasa.gov{rel_link}"
                    return pdf_url
    except Exception:
        pass
    return None


def resolve_standards_doc(session: requests.Session, link: str) -> set[str]:
    """Resolve NASA Technical Standards page and extract the latest approved public PDF (ignoring historical)."""
    urls = set()
    urls.add(link)
    if link.lower().endswith(".pdf"):
        return urls
    resp = fetch_with_retry(session, link)
    if not resp or resp.status_code != 200:
        return urls

    html = resp.text
    # Extract only approved public standard (exclude historical)
    pub_pdf_match = re.search(
        r'PUBLIC:\s*Upload Publicly Available Standard.*?<a\s+[^>]*href=[\"\']([^\"\']+\.pdf[^\s\"\'<>]*)[\"\']',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if pub_pdf_match:
        pdf_rel = pub_pdf_match.group(1).split("?")[0].split("#")[0]
        if "historical" not in pdf_rel.lower():
            urls.add(urljoin("https://standards.nasa.gov", pdf_rel))
    return urls


def resolve_nodis_doc(session: requests.Session, link: str) -> set[str]:
    """Resolve NODIS directive page and discover master unified PDF."""
    urls = set()
    urls.add(link)
    resp = fetch_with_retry(session, link)
    if not resp or resp.status_code != 200:
        return urls
    html = resp.text
    master_pdf = re.search(r'href=[\"\']([^\"\']*OPD_docs/[^\"\']+\.pdf)[\"\']', html, re.IGNORECASE)
    if master_pdf:
        urls.add(urljoin("https://nodis3.gsfc.nasa.gov", master_pdf.group(1)))
    return urls


def main():
    print("=" * 70)
    print(" NASA Safety and Mission Assurance (SMA) Policies Sitemap Generator")
    print(" (NTRS Citations Resolved to Direct PDFs; Latest Approved Revisions Only)")
    print("=" * 70)

    session = requests.Session()
    session.headers.update(HEADERS)

    catalog_url = f"{BASE_URL}/policies/all-policies"
    print(f"[*] Fetching master policy catalog from {catalog_url}...")
    resp = fetch_with_retry(session, catalog_url)
    if not resp or resp.status_code != 200:
        print(f"[!] FATAL: Failed to retrieve {catalog_url}")
        sys.exit(1)

    html = resp.text
    tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL | re.IGNORECASE)
    categories = ["NPDs", "NPRs", "NASA Standards", "NASA Handbooks & Guidance"]

    policy_items = []
    for cat, t in zip(categories, tables):
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.DOTALL | re.IGNORECASE)
        for r in rows[1:]:
            tds = re.findall(r'<td[^>]*>(.*?)</td>', r, re.DOTALL | re.IGNORECASE)
            clean_tds = [' '.join(re.sub(r'<[^>]+>', ' ', td).split()) for td in tds]
            if not clean_tds:
                continue
            policy_id = clean_tds[0]
            title = clean_tds[1] if len(clean_tds) > 1 else ""
            status = clean_tds[2] if len(clean_tds) > 2 else ""
            links = re.findall(r'<a\s+[^>]*href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>', r, re.DOTALL | re.IGNORECASE)
            for href, text in links:
                policy_items.append({
                    "category": cat,
                    "policy_id": policy_id,
                    "title": title,
                    "status": status,
                    "href": href.strip(),
                })

    print(f"[+] Discovered {len(policy_items)} primary policy links across {len(tables)} categories")

    # Aggregate URLs
    all_urls = set(SMA_HUB_PAGES)
    ntrs_resolved_count = 0
    nodis_resolved_count = 0
    standards_resolved_count = 0

    print("[*] Resolving policy links and downloading direct PDFs...")
    for item in policy_items:
        href = item["href"]
        # Skip external subscription paywalls (doclinkonline.com -> IHS Markit)
        if "doclinkonline.com" in href or "ihs.com" in href:
            continue

        if "ntrs.nasa.gov" in href:
            pdf_url = resolve_ntrs_pdf(session, href)
            if pdf_url:
                all_urls.add(pdf_url)
                ntrs_resolved_count += 1
                print(f"    [NTRS API] {item['policy_id']} -> {pdf_url}")
            else:
                all_urls.add(href)
        elif "nodis3.gsfc.nasa.gov" in href:
            nodis_urls = resolve_nodis_doc(session, href)
            all_urls.update(nodis_urls)
            nodis_resolved_count += 1
        elif "standards.nasa.gov" in href:
            std_urls = resolve_standards_doc(session, href)
            all_urls.update(std_urls)
            standards_resolved_count += 1
        else:
            all_urls.add(href)

    sorted_urls = sorted(list(all_urls))
    pdf_urls = [u for u in sorted_urls if u.lower().endswith(".pdf")]
    html_urls = [u for u in sorted_urls if not u.lower().endswith(".pdf")]

    print("\n" + "=" * 70)
    print("[+] Resolution Summary:")
    print(f"    - NTRS Direct Master PDFs Resolved:        {ntrs_resolved_count}")
    print(f"    - NODIS Directives & PDFs Processed:       {nodis_resolved_count}")
    print(f"    - NASA Standards Landing & PDFs Processed: {standards_resolved_count}")
    print(f"    - OSMA Policy & Discipline Context Pages:  {len(SMA_HUB_PAGES)}")
    print(f"\n[+] Total Content URLs Aggregated: {len(sorted_urls)}")
    print(f"    - Master PDF Documents:                    {len(pdf_urls)}")
    print(f"    - HTML Guidance & Landing Pages:           {len(html_urls)}")
    print("=" * 70)

    # Safety threshold check
    if len(sorted_urls) < MINIMUM_EXPECTED_URLS:
        print(f"[!] ERROR: Aggregated URLs ({len(sorted_urls)}) is below safety threshold ({MINIMUM_EXPECTED_URLS}).")
        sys.exit(1)

    # Write sitemap.xml and urls.txt
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sitemap_path = os.path.join(script_dir, "sma_sitemap.xml")
    urls_txt_path = os.path.join(script_dir, "sma_urls.txt")

    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for u in sorted_urls:
        escaped_url = escape(u)
        if u.lower().endswith(".pdf"):
            priority = "0.9"
            changefreq = "monthly"
        elif "all-policies" in u or "policy-status" in u:
            priority = "0.8"
            changefreq = "weekly"
        elif "sma-disciplines" in u:
            priority = "0.7"
            changefreq = "monthly"
        else:
            priority = "0.8"
            changefreq = "monthly"

        xml_lines.append("  <url>")
        xml_lines.append(f"    <loc>{escaped_url}</loc>")
        xml_lines.append(f"    <lastmod>{current_date}</lastmod>")
        xml_lines.append(f"    <changefreq>{changefreq}</changefreq>")
        xml_lines.append(f"    <priority>{priority}</priority>")
        xml_lines.append("  </url>")

    xml_lines.append("</urlset>\n")

    xml_content = "\n".join(xml_lines)

    # Verify XML well-formedness
    try:
        ET.fromstring(xml_content.encode("utf-8"))
        print("[+] XML sitemap validated successfully with ElementTree.")
    except ET.ParseError as pe:
        print(f"[!] FATAL: Generated XML failed parsing check: {pe}")
        sys.exit(1)

    with open(sitemap_path, "w", encoding="utf-8") as f:
        f.write(xml_content)
    print(f"[+] Successfully wrote: {sitemap_path}")

    with open(urls_txt_path, "w", encoding="utf-8") as f:
        for u in sorted_urls:
            f.write(f"{u}\n")
    print(f"[+] Successfully wrote: {urls_txt_path}")


if __name__ == "__main__":
    main()
