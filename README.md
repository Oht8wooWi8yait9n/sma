# NASA Safety and Mission Assurance (SMA) Policies Sitemap & Scraper Solution

Automated, hardened sitemap generator and weekly synchronization pipeline for the **NASA Safety and Mission Assurance (SMA)** policy library:
`https://sma.nasa.gov/policies/all-policies`

This repository generates and maintains an XML sitemap and URL list optimized for ingestion by **Onyx** (formerly Danswer) and other AI search / RAG platforms.

---

## Architecture & How This Solves SMA Ingestion

The master policy catalog at `https://sma.nasa.gov/policies/all-policies` serves as the authoritative gateway to all Safety and Mission Assurance governance across NASA. However, ingesting this site with generic web crawlers leads to several critical issues:

1. **NTRS Citations Resolved to Direct Full-Text PDFs**:
   - The OSMA catalog links several key technical handbooks and special publications to the **NASA Technical Reports Server (NTRS)** (e.g. `/citations/20240014326`, `search.jsp?R=...`).
   - A standard crawler only indexes the NTRS abstract/citation page, leaving the actual technical standard or handbook unindexed.
   - **Solution**: This crawler automatically interfaces with the official NASA NTRS REST API (`https://ntrs.nasa.gov/api/citations/{id}`) to discover and link the direct master PDF download endpoint (`https://ntrs.nasa.gov/api/citations/{id}/downloads/{filename}.pdf`).

2. **Unified Master PDFs for NODIS Directives**:
   - For all NASA Policy Directives (NPDs) and NASA Procedural Requirements (NPRs), the crawler indexes both the directive overview and resolves the full unified PDF (`OPD_docs/..._main.pdf`).

3. **Strict "Latest Revision Only" Policy**:
   - Standards linked via `standards.nasa.gov` are checked to extract only the current approved revision from `PUBLIC: Upload Publicly Available Standard`, automatically discarding all `/Historical/` superseded versions.
   - Any external login or paywalled links (e.g. `doclinkonline.com` / IHS Markit) are bypassed.

4. **Programmatic Discipline Context**:
   - In addition to governance documents, the crawler indexes the 21 primary SMA Discipline landing pages (`/sma-disciplines/quality`, `/sma-disciplines/system-safety`, `/sma-disciplines/software-assurance-and-software-safety`, etc.), giving Onyx full contextual grounding for all safety and mission assurance domains.

---

## Indexed Content Overview

The sitemap indexes **106** curated, verified URLs:

- **31 Direct Master PDF Documents**:
  - Full-text technical handbooks, special publications, and standards (including NTRS direct PDF downloads)
- **75 Clean HTML Pages**:
  - Master policy catalogs (`/policies/all-policies`, `/policies/policy-status`)
  - Directive overviews on NODIS
  - Technical standard landing pages
  - 21 OSMA discipline reference hubs
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

- **GitHub Actions Workflow**: Runs automatically every Sunday at 00:00 UTC (`.github/workflows/update-sitemap.yml`).
- **Safety Threshold**: Validates that at least 75 URLs are collected before writing, preventing accidental blanking of the sitemap.
- **Manual Trigger**: Supports on-demand crawl triggers via GitHub Actions `workflow_dispatch`.
