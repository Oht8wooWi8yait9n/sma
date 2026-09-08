#!/usr/bin/env python3
"""
NASA Safety and Mission Assurance (SMA) Policies Sitemap & Mirror Generator

Features:
1. Harvests all active NASA Safety and Mission Assurance policies from https://sma.nasa.gov/policies/all-policies:
   - NPDs (Policy Directives)
   - NPRs (Procedural Requirements)
   - NASA Technical Standards
   - NASA Handbooks and Guidance
2. Resolves NTRS citations to direct master PDF downloads via official NTRS API (including 20030068423.pdf).
3. Resolves NODIS directives to master unified OPD PDFs and directive landing pages.
4. Resolves NASA Technical Standards pages to approved public PDFs (including 8719.12).
5. Pre-renders all 34 sma.nasa.gov HTML discipline and policy hub pages to static HTML under pages/
   and hosts them on GitHub Pages to bypass Docker IPv6 routing errors ([Errno 101]) and IIS quirks.
6. Outputs dual XML sitemaps:
   - sma_sitemap.xml: Primary Onyx sitemap with GitHub Pages mirrors for sma.nasa.gov + direct PDFs.
   - sma_direct_sitemap.xml: Sitemap with 100% original live URLs.
"""

import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import requests

BASE_URL = "https://sma.nasa.gov"
GH_PAGES_BASE = "https://oht8woowi8yait9n.github.io/sma"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
}

# 34 official SMA policy and discipline hub pages
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

MAX_RETRIES = 3
BACKOFF_BASE = 2


def fetch_with_retry(session: requests.Session, url: str, method: str = "GET") -> requests.Response | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if method.upper() == "HEAD":
                resp = session.head(url, headers=HEADERS, timeout=12, allow_redirects=True)
            else:
                resp = session.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
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
                    return f"https://ntrs.nasa.gov{rel_link}"
    except Exception:
        pass
    return None


def resolve_standards_doc(session: requests.Session, link: str) -> set[str]:
    """Resolve NASA Technical Standards page and extract approved public PDFs (ignoring historical)."""
    urls = set()
    urls.add(link)
    if link.lower().endswith(".pdf"):
        return urls
    resp = fetch_with_retry(session, link)
    if not resp or resp.status_code != 200:
        return urls

    html = resp.text
    # Extract approved public standard (exclude historical)
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


def url_to_rel_path(url: str) -> str:
    """Map sma.nasa.gov URL to local file path under pages/."""
    path = urllib.parse.urlparse(url).path.strip("/")
    parts = path.split("/")
    if len(parts) == 1:
        return f"pages/{parts[0]}/index.html"
    return f"pages/{'/'.join(parts[:-1])}/{parts[-1]}.html"


def prerender_sma_pages(session: requests.Session, sma_urls: list[str], output_dir: Path) -> dict[str, str]:
    """
    Fetch all sma.nasa.gov HTML pages, inject base href for assets,
    and save them locally so GitHub Pages can host them.
    Returns mapping: {live_url: github_pages_url}.
    """
    url_map = {}
    print(f"[*] Pre-rendering {len(sma_urls)} sma.nasa.gov HTML pages for GitHub Pages...")
    for u in sma_urls:
        rel_path = url_to_rel_path(u)
        target_file = output_dir / rel_path
        target_file.parent.mkdir(parents=True, exist_ok=True)

        resp = fetch_with_retry(session, u)
        if resp and resp.status_code == 200:
            html = resp.text
            # Inject <base href="https://sma.nasa.gov/"> right after <head> for clean asset loading
            if "<base " not in html.lower():
                html = re.sub(r'(<head[^>]*>)', r'\1\n  <base href="https://sma.nasa.gov/">', html, count=1, flags=re.IGNORECASE)
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(html)
            gh_url = f"{GH_PAGES_BASE}/{rel_path}"
            url_map[u] = gh_url
            print(f"    [Pre-rendered] {u} -> {rel_path}")
        else:
            print(f"    [!] Failed to pre-render: {u}")
            url_map[u] = u
    return url_map


def build_sitemap_xml(urls: list[str]) -> str:
    """Construct well-formed XML sitemap according to sitemaps.org schema."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urlset = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")

    for url in urls:
        url_elem = ET.SubElement(urlset, "url")
        loc_elem = ET.SubElement(url_elem, "loc")
        loc_elem.text = url

        lastmod_elem = ET.SubElement(url_elem, "lastmod")
        lastmod_elem.text = today

        changefreq_elem = ET.SubElement(url_elem, "changefreq")
        priority_elem = ET.SubElement(url_elem, "priority")

        if url.lower().endswith(".pdf"):
            changefreq_elem.text = "monthly"
            priority_elem.text = "0.9"
        elif "all-policies" in url or "policy-status" in url:
            changefreq_elem.text = "weekly"
            priority_elem.text = "1.0"
        elif "policies" in url:
            changefreq_elem.text = "weekly"
            priority_elem.text = "0.8"
        else:
            changefreq_elem.text = "monthly"
            priority_elem.text = "0.7"

    xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
    rough_string = ET.tostring(urlset, encoding="unicode")
    return xml_declaration + rough_string


def main():
    print("=" * 70)
    print(" NASA Safety and Mission Assurance (SMA) Policies Sitemap & Mirror Generator")
    print("=" * 70)

    repo_dir = Path(__file__).resolve().parent
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

    # Aggregate direct URLs
    direct_urls = set(SMA_HUB_PAGES)
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
                direct_urls.add(pdf_url)
                ntrs_resolved_count += 1
                print(f"    [NTRS API] {item['policy_id']} -> {pdf_url}")
            else:
                direct_urls.add(href)
        elif "nodis3.gsfc.nasa.gov" in href:
            nodis_urls = resolve_nodis_doc(session, href)
            direct_urls.update(nodis_urls)
            nodis_resolved_count += 1
        elif "standards.nasa.gov" in href:
            std_urls = resolve_standards_doc(session, href)
            direct_urls.update(std_urls)
            standards_resolved_count += 1
        else:
            direct_urls.add(href)

    # Pre-render all sma.nasa.gov HTML pages to GitHub Pages static files
    sma_pages_to_prerender = sorted([u for u in direct_urls if "sma.nasa.gov" in u])
    gh_mirror_map = prerender_sma_pages(session, sma_pages_to_prerender, repo_dir)

    # Build Onyx primary URL list (substituting sma.nasa.gov URLs with GitHub Pages mirrors)
    onyx_urls = set()
    for u in direct_urls:
        if u in gh_mirror_map:
            onyx_urls.add(gh_mirror_map[u])
        else:
            onyx_urls.add(u)

    sorted_onyx_urls = sorted(list(onyx_urls))
    sorted_direct_urls = sorted(list(direct_urls))

    pdf_count = sum(1 for u in sorted_onyx_urls if u.lower().endswith(".pdf"))
    html_count = len(sorted_onyx_urls) - pdf_count

    print("\n" + "=" * 70)
    print("[+] Resolution Summary:")
    print(f"    - NTRS Direct Master PDFs Resolved:        {ntrs_resolved_count}")
    print(f"    - NODIS Directives & PDFs Processed:       {nodis_resolved_count}")
    print(f"    - NASA Standards Landing & PDFs Processed: {standards_resolved_count}")
    print(f"    - Pre-rendered GitHub Pages Created:       {len(sma_pages_to_prerender)}")
    print(f"    - Total Content URLs in Sitemap:           {len(sorted_onyx_urls)}")
    print(f"      * Direct Master PDF Documents:           {pdf_count}")
    print(f"      * Policy & Guidance HTML Pages:          {html_count}")
    print("=" * 70)

    # 1. Write Onyx Primary Sitemap (GitHub Pages for sma.nasa.gov HTML + Direct PDFs)
    onyx_sitemap_xml = build_sitemap_xml(sorted_onyx_urls)
    try:
        ET.fromstring(onyx_sitemap_xml.encode("utf-8"))
        print("[+] Primary XML sitemap validated successfully with ElementTree.")
    except ET.ParseError as e:
        print(f"[!] FATAL: XML validation failed: {e}")
        sys.exit(1)

    sitemap_path = repo_dir / "sma_sitemap.xml"
    with open(sitemap_path, "w", encoding="utf-8") as f:
        f.write(onyx_sitemap_xml)
    print(f"[+] Successfully wrote: {sitemap_path}")

    urls_txt_path = repo_dir / "sma_urls.txt"
    with open(urls_txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted_onyx_urls) + "\n")
    print(f"[+] Successfully wrote: {urls_txt_path}")

    # 2. Write Direct Sitemap (100% original URLs)
    direct_sitemap_xml = build_sitemap_xml(sorted_direct_urls)
    direct_sitemap_path = repo_dir / "sma_direct_sitemap.xml"
    with open(direct_sitemap_path, "w", encoding="utf-8") as f:
        f.write(direct_sitemap_xml)
    print(f"[+] Successfully wrote: {direct_sitemap_path}")

    direct_urls_txt_path = repo_dir / "sma_direct_urls.txt"
    with open(direct_urls_txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted_direct_urls) + "\n")
    print(f"[+] Successfully wrote: {direct_urls_txt_path}")


if __name__ == "__main__":
    main()
