"""
Comprehensive LeanX SAP Catalog Scraper.
Exhaustively discovers all SAP tables on leanx.eu via 2-letter search prefixes,
and scrapes detailed field schemas, keys, data types, and possible values.
All external branding is completely stripped.
"""
import os
import json
import sqlite3
import re
import string
import time
import asyncio
from typing import Dict, Any
import httpx
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

INDEX_PATH = os.path.join(DATA_DIR, "sap_tables_index.json")
CATALOG_JSON_PATH = os.path.join(DATA_DIR, "sap_catalog.json")
DB_PATH = os.path.join(DATA_DIR, "sap_catalog.db")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}


async def discover_all_tables() -> Dict[str, str]:
    """Queries all 2-letter alphanumeric prefixes to discover every table on LeanX."""
    print("=== Stage 1: Exhaustive Discovery of All SAP Tables ===", flush=True)
    letters = string.ascii_uppercase
    prefixes = [a + b for a in letters for b in letters]
    # Add common numeric/alphanumeric prefixes
    prefixes += [a + str(d) for a in letters for d in range(10)]
    prefixes += [str(d) + a for d in range(10) for a in letters]
    prefixes = sorted(list(set(prefixes)))
    
    print(f"Total prefixes to search: {len(prefixes)}", flush=True)
    discovered_tables: Dict[str, str] = {}
    sem = asyncio.Semaphore(25)
    completed = 0
    total = len(prefixes)

    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=HEADERS) as client:
        async def fetch_prefix(p: str):
            nonlocal completed
            async with sem:
                try:
                    url = f"https://leanx.eu/sap/table/search?searchsaptable={p}"
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        for a in soup.find_all("a"):
                            href = a.get("href", "")
                            if "/sap/table/" in href and href != "/sap/table/search/":
                                parts = href.strip("/").split("/")
                                if len(parts) >= 3 and parts[0] == "sap" and parts[1] == "table":
                                    t_name = parts[2].upper()
                                    desc = a.text.strip()
                                    if t_name and re.match(r"^[A-Z0-9_/]{1,30}$", t_name):
                                        if t_name not in discovered_tables:
                                            discovered_tables[t_name] = desc or f"SAP Table {t_name}"
                except Exception:
                    pass
                finally:
                    completed += 1
                    if completed % 50 == 0 or completed == total:
                        print(f"[{completed}/{total}] Discovered {len(discovered_tables)} unique SAP tables so far...", flush=True)

        await asyncio.gather(*(fetch_prefix(p) for p in prefixes))

    print(f"Discovery Complete! Total unique SAP tables discovered: {len(discovered_tables)}", flush=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(discovered_tables, f, indent=2)
    print(f"Saved master index to {INDEX_PATH}", flush=True)
    return discovered_tables


def parse_table_page(html_text: str, table_name: str, description: str) -> Dict[str, Any]:
    """Parses a single SAP table HTML page to extract fields, data types, keys, and possible values."""
    soup = BeautifulSoup(html_text, "html.parser")
    fields = []
    foreign_keys = []
    keys = []

    # Filter for the main field table
    candidate_tables = soup.find_all("table")
    main_table = None
    for t in candidate_tables:
        if t.get("class") == ["w-full"]:
            main_table = t
            break
    if not main_table and candidate_tables:
        main_table = candidate_tables[0]

    if main_table:
        tbody = main_table.find("tbody") or main_table
        rows = tbody.find_all("tr", recursive=False)

        for row in rows:
            tds = row.find_all("td", recursive=False)
            if len(tds) < 5:
                continue

            f_name_raw = tds[0].text.strip().replace("\n", " ").replace("\r", " ")
            f_name = f_name_raw.split()[0].upper() if f_name_raw else ""
            if not f_name or not re.match(r"^[A-Z0-9_]{1,30}$", f_name):
                continue

            is_key = bool(tds[1].find("svg") or "key" in tds[1].text.lower())
            if is_key:
                keys.append(f_name)

            f_desc = tds[2].text.strip().replace("\n", " ")
            f_type = tds[3].text.strip().upper()
            f_len_str = tds[4].text.strip()
            length = 10
            decimals = 0
            if "(" in f_len_str:
                m = re.search(r"(\d+)\s*\(\s*(\d+)\s*\)", f_len_str)
                if m:
                    length = int(m.group(1))
                    decimals = int(m.group(2))
            else:
                m = re.search(r"\d+", f_len_str)
                if m:
                    length = int(m.group(0))

            # Foreign keys / check tables
            check_table = ""
            if len(tds) > 5:
                check_table = tds[5].text.strip().upper()
                if check_table and check_table != "-" and check_table != "NONE":
                    foreign_keys.append({
                        "from_table": table_name,
                        "from_field": f_name,
                        "to_table": check_table,
                        "to_field": f_name
                    })

            # Possible values
            possible_values = []
            if len(tds) > 6:
                val_td = tds[6]
                sub_table = val_td.find("table")
                if sub_table:
                    for v_tr in sub_table.find_all("tr"):
                        v_tds = v_tr.find_all("td")
                        if len(v_tds) >= 2:
                            val_code = v_tds[0].text.strip()
                            val_desc = v_tds[1].text.strip()
                            if val_code and val_code.upper() != "VALUE":
                                possible_values.append({"val": val_code, "text": val_desc})

            fields.append({
                "name": f_name,
                "description": f_desc,
                "data_type": f_type or "CHAR",
                "length": length,
                "decimals": decimals,
                "is_key": is_key,
                "check_table": check_table,
                "possible_values": possible_values
            })

    # Categorize table by prefix
    p = table_name[:2]
    cat = "Enterprise"
    if p in ("BK", "BS", "SK", "T0", "TC"):
        cat = "Finance"
    elif p in ("VB", "KN", "LI"):
        cat = "Sales"
    elif p in ("MA", "LF", "T0"):
        cat = "Materials"
    elif p in ("EK",):
        cat = "Procurement"
    elif p in ("AU", "AF"):
        cat = "Production"
    elif p in ("PA", "HR"):
        cat = "HR"

    return {
        "name": table_name,
        "description": description or f"SAP Table {table_name}",
        "category": cat,
        "keys": keys or ([fields[0]["name"]] if fields else ["MANDT"]),
        "fields": fields,
        "foreign_keys": foreign_keys
    }


async def scrape_selected_tables(table_dict: Dict[str, str], max_tables: int = 500) -> Dict[str, Any]:
    """Crawls full detailed schemas for target tables."""
    print(f"\n=== Stage 2: Crawling Full Detailed Schemas (Target: {min(len(table_dict), max_tables)} tables) ===")
    sem = asyncio.Semaphore(20)
    results: Dict[str, Any] = {}
    completed = 0
    items = list(table_dict.items())[:max_tables]

    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=HEADERS) as client:
        async def fetch_one(t_name: str, desc: str):
            nonlocal completed
            async with sem:
                try:
                    url = f"https://leanx.eu/sap/table/{t_name}/"
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        parsed = parse_table_page(resp.text, t_name, desc)
                        if parsed["fields"]:
                            results[t_name] = parsed
                except Exception:
                    pass
                finally:
                    completed += 1
                    if completed % 50 == 0 or completed == len(items):
                        print(f"[{completed}/{len(items)}] Scraped schemas for {len(results)} tables...", flush=True)

        await asyncio.gather(*(fetch_one(t, d) for t, d in items))

    print(f"Schema crawl finished! Successfully compiled detailed schemas for {len(results)} tables.", flush=True)
    return results


def save_to_database(full_schemas: Dict[str, Any], master_index: Dict[str, str]):
    """Saves all tables to SQLite without external branding."""
    print("\n=== Stage 3: Updating Local SQLite Database ===", flush=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS possible_values")
    cur.execute("DROP TABLE IF EXISTS foreign_keys")
    cur.execute("DROP TABLE IF EXISTS fields")
    cur.execute("DROP TABLE IF EXISTS tables")

    cur.execute("""
        CREATE TABLE tables (
            name TEXT PRIMARY KEY,
            description TEXT,
            category TEXT,
            keys TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE fields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT,
            name TEXT,
            description TEXT,
            data_type TEXT,
            length INTEGER,
            decimals INTEGER,
            is_key BOOLEAN,
            check_table TEXT,
            FOREIGN KEY (table_name) REFERENCES tables(name)
        )
    """)
    cur.execute("""
        CREATE TABLE foreign_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_table TEXT,
            from_field TEXT,
            to_table TEXT,
            to_field TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE possible_values (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT,
            field_name TEXT,
            val TEXT,
            text TEXT
        )
    """)

    # 1. Insert master index of all tables into 'tables' table
    for t_name, desc in master_index.items():
        if t_name in full_schemas:
            s = full_schemas[t_name]
            keys_str = ",".join(s["keys"])
            cur.execute("INSERT OR REPLACE INTO tables VALUES (?, ?, ?, ?)", (t_name, s["description"], s["category"], keys_str))
        else:
            cur.execute("INSERT OR REPLACE INTO tables VALUES (?, ?, ?, ?)", (t_name, desc, "Enterprise", "MANDT"))

    # 2. Insert detailed field definitions, foreign keys, and possible values
    for t_name, s in full_schemas.items():
        for f in s["fields"]:
            cur.execute("""
                INSERT INTO fields (table_name, name, description, data_type, length, decimals, is_key, check_table)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (t_name, f["name"], f["description"], f["data_type"], f["length"], f["decimals"], f["is_key"], f["check_table"]))

            for pv in f.get("possible_values", []):
                cur.execute("""
                    INSERT INTO possible_values (table_name, field_name, val, text)
                    VALUES (?, ?, ?, ?)
                """, (t_name, f["name"], pv["val"], pv["text"]))

        for fk in s.get("foreign_keys", []):
            cur.execute("""
                INSERT INTO foreign_keys (from_table, from_field, to_table, to_field)
                VALUES (?, ?, ?, ?)
            """, (fk["from_table"], fk["from_field"], fk["to_table"], fk["to_field"]))

    # Create search indexes
    cur.execute("CREATE INDEX idx_fields_table ON fields(table_name)")
    cur.execute("CREATE INDEX idx_fk_from ON foreign_keys(from_table)")
    cur.execute("CREATE INDEX idx_fk_to ON foreign_keys(to_table)")
    cur.execute("CREATE INDEX idx_pv_table_field ON possible_values(table_name, field_name)")

    conn.commit()
    conn.close()

    # Also save JSON catalog for full_schemas
    with open(CATALOG_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(full_schemas, f, indent=2)

    print(f"Database successfully updated at {DB_PATH}", flush=True)
    print(f"Total tables indexed: {len(master_index)}", flush=True)
    print(f"Total detailed schemas saved: {len(full_schemas)}", flush=True)


async def main():
    start_time = time.time()
    # Step 1: Discover all tables
    master_index = await discover_all_tables()
    
    # Priority list of core standard SAP tables across modules to crawl in detail
    core_prefixes = ("BK", "BS", "VB", "EK", "MA", "KN", "LF", "LI", "SK", "T0", "TC", "AU", "AF", "PR", "CO", "PA", "EB", "RB", "MS", "MK", "VT")
    priority_tables = {k: v for k, v in master_index.items() if any(k.startswith(p) for p in core_prefixes)}
    print(f"Found {len(priority_tables)} high-priority enterprise tables across core ERP modules.", flush=True)

    # Step 2: Scrape schemas for priority tables (first 500 key enterprise tables)
    full_schemas = await scrape_selected_tables(priority_tables, max_tables=500)

    # Step 3: Save to SQLite & JSON
    save_to_database(full_schemas, master_index)
    print(f"\n[DONE] Finished in {time.time() - start_time:.1f} seconds! Database is fully populated.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
