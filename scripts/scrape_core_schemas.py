"""
Pre-caches detailed field schemas, keys, foreign keys, and domain values
for the top 60 core SAP enterprise tables directly into data/sap_catalog.db.
"""
import os
import sqlite3
import re
import asyncio
import time
import httpx
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "sap_catalog.db")

CORE_TABLES = [
    # FI / GL / AP / AR
    "BKPF", "BSEG", "SKA1", "SKB1", "T001", "T003", "TCURC", "BSIS", "BSAS", "BSIK", "BSAK", "BSID", "BSAD",
    # CO / Controlling
    "COBK", "COEP", "CSKS", "CSKT", "AUFK", "AFKO", "AFPO",
    # SD / Sales & Billing
    "VBAK", "VBAP", "VBEP", "VBKD", "LIKP", "LIPS", "VBRK", "VBRP", "KNA1", "KNB1", "KNVV", "KNVP",
    # MM / Materials
    "MARA", "MAKT", "MARC", "MARD", "MBEW", "MKPF", "MSEG", "LFA1", "LFB1", "LFM1", "T001W", "T001L",
    # Purchasing
    "EKKO", "EKPO", "EKET", "EKBE", "EBAN", "EBKN", "EINA", "EINE",
    # Logistics / Shipments
    "VTTK", "VTTP", "VEKP", "VEPO"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}


def parse_table_page(html_text: str, table_name: str) -> dict:
    soup = BeautifulSoup(html_text, "html.parser")
    fields = []
    foreign_keys = []
    keys = []

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
        for row in tbody.find_all("tr", recursive=False):
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

            possible_values = []
            if len(tds) > 6:
                sub_table = tds[6].find("table")
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

    return {
        "name": table_name,
        "keys": keys or ([fields[0]["name"]] if fields else ["MANDT"]),
        "fields": fields,
        "foreign_keys": foreign_keys
    }


async def scrape_and_save():
    print(f"Scraping detailed schemas for {len(CORE_TABLES)} core ERP tables...", flush=True)
    t0 = time.time()
    sem = asyncio.Semaphore(15)
    results = {}

    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=HEADERS) as client:
        async def fetch(t_name):
            async with sem:
                try:
                    r = await client.get(f"https://leanx.eu/sap/table/{t_name}/")
                    if r.status_code == 200:
                        parsed = parse_table_page(r.text, t_name)
                        if parsed["fields"]:
                            results[t_name] = parsed
                except Exception as e:
                    print(f"Failed to fetch {t_name}: {e}", flush=True)

        await asyncio.gather(*(fetch(t) for t in CORE_TABLES))

    print(f"Scraped {len(results)} tables in {time.time()-t0:.1f}s. Saving to SQLite...", flush=True)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT,
            name TEXT,
            description TEXT,
            data_type TEXT,
            length INTEGER,
            decimals INTEGER,
            is_key BOOLEAN,
            check_table TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS foreign_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_table TEXT,
            from_field TEXT,
            to_table TEXT,
            to_field TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS possible_values (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT,
            field_name TEXT,
            val TEXT,
            text TEXT
        )
    """)

    for t_name, s in results.items():
        # Clean existing fields for this table
        cur.execute("DELETE FROM fields WHERE table_name = ?", (t_name,))
        cur.execute("DELETE FROM foreign_keys WHERE source_table = ?", (t_name,))
        cur.execute("DELETE FROM possible_values WHERE table_name = ?", (t_name,))

        # Update keys in tables table
        keys_str = ",".join(s["keys"])
        cur.execute("UPDATE tables SET keys = ? WHERE name = ?", (keys_str, t_name))

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
                INSERT INTO foreign_keys (source_table, field, ref_table, ref_field)
                VALUES (?, ?, ?, ?)
            """, (fk["from_table"], fk["from_field"], fk["to_table"], fk["to_field"]))

    conn.commit()
    total_fields = cur.execute("SELECT count(*) FROM fields").fetchone()[0]
    total_fks = cur.execute("SELECT count(*) FROM foreign_keys").fetchone()[0]
    conn.close()

    print(f"Successfully cached {len(results)} tables with {total_fields} fields and {total_fks} foreign keys!", flush=True)


if __name__ == "__main__":
    asyncio.run(scrape_and_save())
