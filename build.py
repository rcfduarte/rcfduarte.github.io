#!/usr/bin/env python3
"""
Build script for rcfduarte.github.io

Fetches data from the Airtable base powering comp-neuro.org and regenerates
the publications section of the personal site.

Usage:
    python build.py                          # Show help
    python build.py --rebuild                # Rebuild from local data/*.json
    python build.py --sync                   # Fetch from Airtable first, then build
    AIRTABLE_TOKEN=pat... python build.py --sync  # With explicit token

Requirements:
    pip install requests

Environment variables:
    AIRTABLE_TOKEN    - Personal access token with read access to website base
    AIRTABLE_BASE_ID  - Base ID (default: apptd4Eb6LQjzmcKF)

Note:
    The Airtable PAT must have scope to read the website base (apptd4Eb6LQjzmcKF).
    If using the MCP token from Desktop/.mcp.json, ensure the token's base access
    includes both the funding opportunities base and the website base.
"""

import argparse
import html
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
INDEX_PATH = ROOT / "index.html"

AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "apptd4Eb6LQjzmcKF")
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN", "")


def fetch_airtable_table(table_name: str, params: dict | None = None) -> list[dict]:
    """Fetch all records from an Airtable table with pagination."""
    import requests

    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{table_name}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}"}
    params = dict(params or {})

    records = []
    while True:
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break
        params["offset"] = offset

    return [r["fields"] for r in records]


def sync_from_airtable():
    """Download publications from Airtable and save to data/publications.json."""
    if not AIRTABLE_TOKEN:
        print("ERROR: Set AIRTABLE_TOKEN environment variable", file=sys.stderr)
        sys.exit(1)

    DATA_DIR.mkdir(exist_ok=True)

    # Fetch all publications sorted by date descending
    print("Fetching Publications...")
    all_records = fetch_airtable_table("Publications", {
        "sort[0][field]": "Release Date",
        "sort[0][direction]": "desc",
    })

    # Filter to published + public
    pubs = []
    for f in all_records:
        if f.get("Status") == "Published" and f.get("Public?"):
            pubs.append({
                "title": f.get("Title", ""),
                "apa": f.get("APA-style Reference", ""),
                "journal": f.get("Publication", ""),
                "doi": f.get("DOI", ""),
                "url": f.get("URL", ""),
                "date": f.get("Release Date", ""),
                "year": f.get("Release Date", "")[:4] if f.get("Release Date") else "",
                "type": f.get("Type", ""),
                "featured": bool(f.get("Featured")),
                "impact": f.get("Impact", 0),
            })

    (DATA_DIR / "publications.json").write_text(
        json.dumps(pubs, indent=2, ensure_ascii=False)
    )
    print(f"  -> {len(pubs)} published+public records saved")
    print(f"  -> {sum(1 for p in pubs if p['featured'])} featured")
    return pubs


def normalize_doi_url(doi: str, fallback_url: str = "") -> str:
    """Normalize a DOI string to a full https URL."""
    if not doi:
        return fallback_url
    doi = doi.strip()
    if doi.startswith("http"):
        return doi
    if doi.startswith("doi.org/"):
        return f"https://{doi}"
    if doi.startswith("10."):
        return f"https://doi.org/{doi}"
    return doi or fallback_url


def extract_authors_from_apa(apa: str) -> str:
    """Extract author string from an APA reference (everything before the year)."""
    # Standard APA: Authors (Year).
    match = re.match(r"^(.+?)\s*\(\d{4}", apa)
    if match:
        return match.group(1).rstrip(",. ")
    # Non-standard: Authors. Title. Journal, Vol(Issue) (Year).
    match = re.match(r"^(.+?)\.\s+\w", apa)
    if match:
        authors = match.group(1).rstrip(",. ")
        # Ensure we didn't grab the title
        if len(authors.split()) < 30:
            return authors
    return ""


def make_pub_card_html(pub: dict) -> str:
    """Generate HTML for a featured publication card."""
    title = html.escape(pub["title"])
    journal = html.escape(pub["journal"])
    year = html.escape(pub["year"])
    doi_url = normalize_doi_url(pub["doi"], pub["url"])

    # Extract authors from APA, highlight Duarte
    authors = extract_authors_from_apa(pub["apa"])
    authors_html = html.escape(authors)
    # Bold "Duarte, R." or "R. Duarte" variants
    authors_html = re.sub(
        r"(Duarte,?\s*R\.?\s*(?:C\.\s*F\.?)?)",
        r"<strong>\1</strong>",
        authors_html,
    )

    link_html = ""
    if doi_url:
        link_html = f' &middot; <a href="{html.escape(doi_url)}">doi</a>'

    return f"""                    <article class="pub-item">
                        <span class="pub-year">{year}</span>
                        <div class="pub-body">
                            <p class="pub-title">{title}</p>
                            <p class="pub-meta">{authors_html}</p>
                            <p class="pub-venue"><em>{journal}</em>{link_html}</p>
                        </div>
                    </article>"""


def make_apa_entry_html(pub: dict) -> str:
    """Generate HTML for an APA-formatted list entry."""
    apa = html.escape(pub["apa"]) if pub["apa"] else html.escape(pub["title"])
    doi_url = normalize_doi_url(pub["doi"], pub["url"])

    # Only append link if the APA text doesn't already contain a URL
    link_html = ""
    if doi_url and "https://" not in pub.get("apa", "") and "http://" not in pub.get("apa", ""):
        display = html.escape(doi_url)
        link_html = f' <a href="{html.escape(doi_url)}">{display}</a>'
    elif doi_url:
        # APA already has a URL in text; just make it a clickable link
        link_label = "doi" if "doi.org" in doi_url else "link"
        link_html = f' <a href="{html.escape(doi_url)}">{link_label}</a>'

    return f"""                        <li class="all-pubs-entry">
                            {apa}{link_html}
                        </li>"""


def build_publications_html(pubs: list[dict]) -> str:
    """Generate the full publications section HTML."""
    featured = [p for p in pubs if p["featured"]]
    total = len(pubs)

    cards = "\n\n".join(make_pub_card_html(p) for p in featured)
    entries = "\n".join(make_apa_entry_html(p) for p in pubs)

    return f"""        <!-- Publications -->
        <section id="publications" class="section">
            <div class="container">
                <h2 class="section-title">Selected Publications</h2>
                <p class="section-subtitle">
                    For the full list and live citation metrics, see <a href="https://scholar.google.de/citations?user=NeD4kokAAAAJ&hl=en">Google Scholar</a>.
                </p>

                <div class="pub-list">
{cards}
                </div>

                <details class="all-pubs">
                    <summary class="all-pubs-toggle">All Publications ({total})</summary>
                    <ol class="all-pubs-list" reversed>
{entries}
                    </ol>
                </details>
            </div>
        </section>"""


def update_profile_metrics(content: str) -> str:
    """Update sidebar metrics from data/profile.json."""
    profile_path = DATA_DIR / "profile.json"
    if not profile_path.exists():
        print("  No profile.json found, skipping metrics update")
        return content

    profile = json.loads(profile_path.read_text())
    metrics = profile.get("metrics", {})

    replacements = {
        "h-index": str(metrics.get("h_index", "")),
        "i10-index": str(metrics.get("i10_index", "")),
        "Citations": str(metrics.get("citations", "")),
        "Papers": str(metrics.get("papers", "")),
        "Years active": str(metrics.get("years_active", "")),
    }

    for label, value in replacements.items():
        if not value:
            continue
        pattern = rf'(<span class="sidebar-label">{re.escape(label)}</span>\s*<span class="sidebar-value">)[^<]*(</span>)'
        new_content = re.sub(pattern, rf'\g<1>{value}\2', content)
        if new_content != content:
            content = new_content
            print(f"  Updated {label}: {value}")

    return content


def rebuild_index(pubs: list[dict]):
    """Replace the all-pubs list entries in index.html."""
    content = INDEX_PATH.read_text()

    # Try the marker-based approach first (<!-- PUBS_START --> ... <!-- PUBS_END -->)
    marker_pattern = r"<!-- PUBS_START -->.*?<!-- PUBS_END -->"
    entries = "\n".join(make_apa_entry_html(p) for p in pubs)
    marker_replacement = f"<!-- PUBS_START -->\n{entries}\n<!-- PUBS_END -->"

    new_content, count = re.subn(marker_pattern, marker_replacement, content, flags=re.DOTALL)
    if count > 0:
        # Also update the count in the toggle text
        new_content = re.sub(
            r'All Publications \(\d+\)',
            f'All Publications ({len(pubs)})',
            new_content,
        )
        # Update profile metrics
        new_content = update_profile_metrics(new_content)

        INDEX_PATH.write_text(new_content)
        print(f"Updated index.html (marker-based): {len(pubs)} entries in all-pubs list")
        return

    # Fallback: replace entire publications section
    pattern = r"        <!-- Publications -->.*?        </section>"
    new_section = build_publications_html(pubs)

    new_content, count = re.subn(pattern, new_section, content, flags=re.DOTALL)
    if count == 0:
        print("WARNING: Could not find publications section to replace", file=sys.stderr)
        return

    # Update profile metrics
    new_content = update_profile_metrics(new_content)

    INDEX_PATH.write_text(new_content)
    print(f"Updated index.html: {sum(1 for p in pubs if p['featured'])} featured, {len(pubs)} total")


def update_sitemap():
    """Update sitemap.xml with today's date."""
    sitemap = ROOT / "sitemap.xml"
    sitemap.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://rcfduarte.github.io/</loc>
        <lastmod>{date.today().isoformat()}</lastmod>
        <changefreq>monthly</changefreq>
        <priority>1.0</priority>
    </url>
</urlset>""")
    print(f"Sitemap updated: {date.today().isoformat()}")


def list_tables():
    """List all tables in the Airtable base."""
    import requests

    if not AIRTABLE_TOKEN:
        print("ERROR: Set AIRTABLE_TOKEN environment variable", file=sys.stderr)
        sys.exit(1)

    url = f"https://api.airtable.com/v0/meta/bases/{AIRTABLE_BASE_ID}/tables"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()

    for table in resp.json().get("tables", []):
        print(f"\nTABLE: {table['name']} (id: {table['id']})")
        for field in table.get("fields", []):
            print(f"  - {field['name']} ({field['type']})")


def load_mcp_token():
    """Try loading the Airtable token from the Desktop MCP config."""
    global AIRTABLE_TOKEN
    mcp_path = Path.home() / "Desktop" / ".mcp.json"
    if mcp_path.exists():
        try:
            config = json.loads(mcp_path.read_text())
            token = config["mcpServers"]["airtable"]["env"]["AIRTABLE_API_KEY"]
            if token:
                AIRTABLE_TOKEN = token
                print(f"Loaded Airtable token from {mcp_path}")
                return True
        except (KeyError, json.JSONDecodeError):
            pass
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build rcfduarte.github.io")
    parser.add_argument("--sync", action="store_true",
                        help="Fetch from Airtable and rebuild index.html")
    parser.add_argument("--list-tables", action="store_true",
                        help="List Airtable tables and fields")
    parser.add_argument("--rebuild", action="store_true",
                        help="Rebuild index.html from local data/*.json (no Airtable fetch)")
    args = parser.parse_args()

    # Auto-load token from MCP config if not in environment
    if not AIRTABLE_TOKEN and (args.sync or args.list_tables):
        load_mcp_token()

    if args.list_tables:
        list_tables()
    elif args.sync:
        pubs = sync_from_airtable()
        rebuild_index(pubs)
        update_sitemap()
    elif args.rebuild:
        pubs = json.loads((DATA_DIR / "publications.json").read_text())
        rebuild_index(pubs)
        update_sitemap()
    else:
        parser.print_help()
