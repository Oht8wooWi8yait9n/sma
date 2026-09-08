# NASA Safety and Mission Assurance (SMA) Policies Sitemap & Scraper Solution

Automated, hardened sitemap generator and weekly synchronization pipeline for the **NASA Safety and Mission Assurance (SMA)** policy library:
`https://sma.nasa.gov/policies/all-policies`

This repository generates and maintains XML sitemaps and pre-rendered static mirrors optimized for ingestion by **Onyx** (formerly Danswer) and other AI search / RAG platforms.

---

## Architecture & How This Solves SMA Ingestion

The master policy catalog at `https://sma.nasa.gov/policies/all-policies` serves as the authoritative gateway to all Safety and Mission Assurance governance across NASA. Ingesting this site directly with generic web crawlers poses several critical hurdles:

1. **Static HTML Pre-Rendering via GitHub Pages (Bypassing Docker IPv6 & IIS Quirks)**:
   - `sma.nasa.gov` advertises both IPv4 and IPv6 DNS records (`2001:4d0:8300:1::153`). In Docker bridge networks without an IPv6 gateway, crawlers attempting to connect to `sma.nasa.gov` fail with `[Errno 101] Network is unreachable`. Additionally, the IIS/ASP.NET backend issues session cookies and behaves inconsistently with automated `HEAD` probes.
   - **Solution**: The workflow pre-renders all 34 `sma.nasa.gov` HTML discipline and policy pages into `pages/`, injects canonical `<base>` tags, and publishes them via GitHub Pages (`https://oht8woowi8yait9n.github.io/sma/pages/...`). Onyx ingests the complete semantic HTML from GitHub Pages Anycast IPv4 CDN at maximum speed with zero connection drops.

2. **NTRS Citations Resolved to Direct Full-Text PDFs**:
   - The OSMA catalog links several key technical handbooks and special publications to the **NASA Technical Reports Server (NTRS)** (e.g. `/citations/20240014326`, `search.jsp?R=...`).
   - A standard crawler only indexes the NTRS abstract/citation page, leaving the actual technical standard or handbook unindexed.
   - **Solution**: This crawler automatically interfaces with the official NASA NTRS REST API (`https://ntrs.nasa.gov/api/citations/{id}`) to discover and link the direct master PDF download endpoint (including the complete 111.3 MB *Meteoroid/Debris Shielding* handbook).

3. **Unified Master PDFs for NODIS Directives**:
   - For all NASA Policy Directives (NPDs) and NASA Procedural Requirements (NPRs), the crawler indexes both the directive overview and resolves the full unified PDF (`OPD_docs/..._main.pdf`).

4. **Strict "Latest Revision Only" Policy**:
   - Standards linked via `standards.nasa.gov` are checked to extract only the current approved revision from `PUBLIC: Upload Publicly Available Standard`, automatically discarding all `/Historical/` superseded versions.
   - Any external subscription paywalls (e.g. `doclinkonline.com` / IHS Markit) are bypassed.

---

## Dual Sitemaps & Data Formats

| File | Purpose | Target Audience |
| :--- | :--- | :--- |
| **[`sma_sitemap.xml`](https://raw.githubusercontent.com/Oht8wooWi8yait9n/sma/main/sma_sitemap.xml)** | **Primary Onyx Sitemap**: Pre-rendered GitHub Pages for `sma.nasa.gov` + direct PDFs from NODIS, Standards, NTRS. | **Onyx Web Connector** |
| **[`sma_urls.txt`](https://raw.githubusercontent.com/Oht8wooWi8yait9n/sma/main/sma_urls.txt)** | Plain text URL list of the primary sitemap. | Quick audits & verification |
| **[`sma_direct_sitemap.xml`](https://raw.githubusercontent.com/Oht8wooWi8yait9n/sma/main/sma_direct_sitemap.xml)** | Direct live URLs sitemap pointing to original `sma.nasa.gov` paths. | Internal direct indexing |
| **[`sma_direct_urls.txt`](https://raw.githubusercontent.com/Oht8wooWi8yait9n/sma/main/sma_direct_urls.txt)** | Plain text list of original live URLs. | Direct downloads |

---

## Indexed Content Overview

The sitemap indexes **108** curated, verified URLs:

- **31 Direct Master PDF Documents**:
  - Full-text technical handbooks, special publications, and standards (including NTRS direct PDF downloads)
- **77 Clean HTML Pages**:
  - 34 Pre-rendered OSMA discipline hubs and policy catalogs (`/policies/all-policies`, `/sma-disciplines/safety-culture`, etc.)
  - Directive overviews on NODIS
  - Technical standard landing pages
- **0 Historical Revisions / Cancelled Documents**: 100% excluded to protect search accuracy.

---

## Onyx Web Connector Configuration

In your Onyx Admin Console (**Connectors** → **Web**):

| Field | Configuration |
| :--- | :--- |
| **Connector Name** | `NASA-SMA` |
| **Base URL** | `https://raw.githubusercontent.com/Oht8wooWi8yait9n/sma/main/sma_sitemap.xml` |
| **Scrape Method** | `sitemap` |

Click **Create Connector** to begin indexing the full NASA Safety and Mission Assurance policy library into Onyx.

---

## Automated Maintenance & CI/CD

- **Workflow**: [`.github/workflows/update-sitemap.yml`](.github/workflows/update-sitemap.yml)
- **Schedule**: Runs automatically every **Sunday at 00:00 UTC** (or on demand via `workflow_dispatch`).
- **Action**: Crawls `sma.nasa.gov`, resolves new revisions, pre-renders HTML updates, regenerates dual sitemaps, and pushes any diffs directly to `main` with automatic GitHub Pages deployment.
