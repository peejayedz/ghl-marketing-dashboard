#!/usr/bin/env python3
"""
Pulls enrollment / open / click stats for GoHighLevel workflows out of the
Contacts API and writes them to data/dashboard-data.json for the static
dashboard to read.

WHY TAGS: GoHighLevel's public API (v2) does not expose a "contacts enrolled
in this workflow" endpoint, nor per-workflow email open/click statistics.
The only reliable, documented way to get these numbers is:

  1. Each workflow tags a contact the moment they enter
     (e.g. an "Add Tag" action as the very first step) -> enrolledTag
  2. A companion trigger/branch fires on the GHL "Email Events" trigger
     (Opened / Clicked), filtered to that campaign's emails, and adds a
     tag -> openedTag / clickedTag
     See: https://help.gohighlevel.com/support/solutions/articles/155000002678-workflow-trigger-email-events

This script then counts contacts per tag via POST /contacts/search.

BEFORE FIRST REAL RUN:
  The GoHighLevel OpenAPI spec for /contacts/search does not fully document
  the request body (it points to an external ClickUp doc). The filter
  shape used below (`filters: [{field, operator, value}]`) is the commonly
  documented v2 pattern, but you should confirm it with one real curl call
  before trusting the automated schedule. Run this script once with
  DEBUG=1 to print the raw request/response and sanity check it against
  a tag you can verify by eye in the GHL UI.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

API_BASE = "https://services.leadconnectorhq.com"
API_VERSION = "2021-07-28"

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
OUTPUT_PATH = ROOT / "data" / "dashboard-data.json"

DEBUG = os.environ.get("DEBUG") == "1"
MOCK = os.environ.get("MOCK") == "1"


def log(*args):
    print(*args, file=sys.stderr)


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def search_contacts_by_tag(token, location_id, tag, page_limit=100, want_contacts=False):
    """Returns (count, contacts_list). contacts_list is [] unless want_contacts=True."""
    if not tag:
        return 0, []

    headers = {
        "Authorization": f"Bearer {token}",
        "Version": API_VERSION,
        "Content-Type": "application/json",
    }

    total = 0
    contacts = []
    search_after = None

    while True:
        body = {
            "locationId": location_id,
            "pageLimit": page_limit,
            "filters": [
                {"field": "tags", "operator": "contains", "value": tag}
            ],
        }
        if search_after:
            body["searchAfter"] = search_after

        if DEBUG:
            log("REQUEST /contacts/search", json.dumps(body))

        resp = requests.post(f"{API_BASE}/contacts/search", headers=headers, json=body, timeout=30)

        if DEBUG:
            log("RESPONSE", resp.status_code, resp.text[:2000])

        resp.raise_for_status()
        data = resp.json()

        page = data.get("contacts", [])
        total = data.get("total", total + len(page))

        if want_contacts:
            for c in page:
                contacts.append({
                    "id": c.get("id"),
                    "name": (c.get("contactName") or
                             f"{c.get('firstName', '')} {c.get('lastName', '')}".strip() or
                             c.get("email") or "(no name)"),
                    "email": c.get("email"),
                    "dateAdded": c.get("dateAdded"),
                })

        if len(page) < page_limit or not page:
            break

        # v2 search is cursor-based; adjust this if your account's response
        # shape differs (see DEBUG=1 note above).
        last = page[-1]
        search_after = last.get("searchAfter") or [last.get("dateAdded"), last.get("id")]

        time.sleep(0.2)  # stay well under burst rate limit

    return total, contacts


def build_mock_data(config):
    import random
    campaigns = []
    for c in config["campaigns"]:
        enrolled = random.randint(80, 400)
        opened = int(enrolled * random.uniform(0.35, 0.65))
        clicked = int(opened * random.uniform(0.15, 0.4))
        campaigns.append({
            "key": c["key"],
            "label": c["label"],
            "enrolled": enrolled,
            "opened": opened,
            "clicked": clicked,
            "replied": int(clicked * 0.2) if c.get("repliedTag") else None,
            "openRate": round(opened / enrolled * 100, 1),
            "clickRate": round(clicked / enrolled * 100, 1),
            "contacts": [
                {"id": f"mock-{i}", "name": f"Mock Contact {i}",
                 "email": f"contact{i}@example.com",
                 "dateAdded": "2026-07-2" + str(i % 9) + "T00:00:00Z"}
                for i in range(min(enrolled, 15))
            ],
        })
    return campaigns


def main():
    config = load_config()

    if MOCK:
        log("MOCK=1 set -> generating fake data, no API calls made")
        campaigns_out = build_mock_data(config)
    else:
        token = os.environ.get("GHL_TOKEN")
        location_id = os.environ.get("GHL_LOCATION_ID") or config.get("locationId")
        if not token or not location_id or location_id.startswith("REPLACE_"):
            log("ERROR: set GHL_TOKEN and GHL_LOCATION_ID environment variables "
                "(and/or fill in locationId in config.json)")
            sys.exit(1)

        campaigns_out = []
        for c in config["campaigns"]:
            log(f"Fetching stats for {c['label']}...")
            enrolled, contacts = search_contacts_by_tag(
                token, location_id, c["enrolledTag"], want_contacts=True)
            opened, _ = search_contacts_by_tag(token, location_id, c["openedTag"])
            clicked, _ = search_contacts_by_tag(token, location_id, c["clickedTag"])
            replied = None
            if c.get("repliedTag"):
                replied, _ = search_contacts_by_tag(token, location_id, c["repliedTag"])

            campaigns_out.append({
                "key": c["key"],
                "label": c["label"],
                "enrolled": enrolled,
                "opened": opened,
                "clicked": clicked,
                "replied": replied,
                "openRate": round(opened / enrolled * 100, 1) if enrolled else 0,
                "clickRate": round(clicked / enrolled * 100, 1) if enrolled else 0,
                "contacts": contacts,
            })

    output = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "campaigns": campaigns_out,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    log(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
