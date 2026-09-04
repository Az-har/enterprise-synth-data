"""
Discovers ALL SAP tables available on leanx.eu by searching all 2-letter combinations (AA..ZZ).
Saves the complete master index to data/sap_tables_index.json and populates the SQLite database.
"""
import os
import json
import sqlite3
import re
import string
import time
import asyncio
from typing import Dict
import httpx
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

INDEX_PATH = os.path.join(DATA_DIR, "sap_tables_index.json")
DB_PATH = os.path.join(DATA_DIR, "sap_catalog.db")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}


async def discover_all() -> Dict[str, str]:
    letters = string.ascii_uppercase
    prefixes = [a + b for a in letters for b in letters]
    print(f"Searching {len(prefixes)} 2-letter prefixes (AA to ZZ)...", flush=True)

    tables: Dict[str, str] = {}
    sem = asyncio.Semaphore(15)
    completed = 0
    total = len(prefixes)
    t0 = time.time()

    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=HEADERS) as client:
        async def fetch(p: str):
            nonlocal completed
            async with sem:
                try:
                    url = f"https://leanx.eu/sap/table/search/?searchsaptable={p}"
                    r = await client.get(url)
                    if r.status_code == 200:
                        soup = BeautifulSoup(r.text, "html.parser")
                        for a in soup.find_all("a"):
                            href = a.get("href", "")
                            if "/sap/table/" in href and href != "/sap/table/search/":
                                parts = href.strip("/").split("/")
                                if len(parts) >= 3 and parts[0] == "sap" and parts[1] == "table":
                                    t_name = parts[2].upper()
                                    desc = a.text.strip()
                                    if t_name and re.match(r"^[A-Z0-9_/]{1,30}$", t_name):
                                        if t_name not in tables:
                                            tables[t_name] = desc or f"SAP Table {t_name}"
                except Exception:
                    pass
                finally:
                    completed += 1
                    if completed % 50 == 0 or completed == total:
                        elapsed = time.time() - t0
                        print(f"[{completed}/{total}] Discovered {len(tables)} unique SAP tables ({elapsed:.1f}s)...", flush=True)

        await asyncio.gather(*(fetch(p) for p in prefixes))

    print(f"\nDiscovery Complete in {time.time()-t0:.1f}s! Total unique SAP tables found: {len(tables)}", flush=True)
    
    # Save JSON index
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(tables, f, indent=2)
    print(f"Saved master index to {INDEX_PATH}", flush=True)

    # Insert into SQLite database tables table
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tables (
            name TEXT PRIMARY KEY,
            description TEXT,
            category TEXT,
            keys TEXT
        )
    """)
    for t_name, desc in tables.items():
        # Determine category based on prefix
        p = t_name[:2]
        cat = "Enterprise"
        if p in ("BK", "BS", "SK", "TC"):
            cat = "Finance"
        elif p in ("VB", "KN", "LI"):
            cat = "Sales & Logistics"
        elif p in ("MA", "LF", "T0"):
            cat = "Materials & Master Data"
        elif p in ("EK",):
            cat = "Procurement"
        elif p in ("AU", "AF"):
            cat = "Production"
        elif p in ("PA", "HR"):
            cat = "HR / HCM"
        elif p in ("CO",):
            cat = "Controlling"

        cur.execute("INSERT OR IGNORE INTO tables VALUES (?, ?, ?, ?)", (t_name, desc, cat, "MANDT"))

    conn.commit()
    conn.close()
    print(f"Populated SQLite database tables index at {DB_PATH}", flush=True)
    return tables


if __name__ == "__main__":
    asyncio.run(discover_all())
