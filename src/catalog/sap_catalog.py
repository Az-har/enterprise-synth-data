"""
SAP Catalog Query Manager.
Fast, memory-efficient offline query interface using the frozen SQLite database and JSON catalog.
"""
import os
import sqlite3
from typing import Dict, List, Optional, Any
from .schema_models import TableSchema, FieldMeta, ForeignKey, PossibleValue

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "sap_catalog.db")


class SAPCatalogManager:
    """Manages queries to the frozen offline SAP Reference Dictionary."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Offline SAP catalog database not found at {self.db_path}. Run build_sap_catalog.py first.")

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def list_tables(self) -> List[Dict[str, str]]:
        """Returns list of all available SAP tables with descriptions and categories."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name, description, category, keys FROM tables ORDER BY category, name")
            rows = cur.fetchall()
            return [
                {
                    "name": row["name"],
                    "description": row["description"],
                    "category": row["category"],
                    "keys": row["keys"].split(",") if row["keys"] else []
                }
                for row in rows
            ]

    def get_table(self, table_name: str) -> Optional[TableSchema]:
        """Loads complete TableSchema including fields, primary keys, and foreign keys."""
        normalized_name = table_name.strip().upper()
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name, description, category, keys FROM tables WHERE UPPER(name) = ?", (normalized_name,))
            tbl_row = cur.fetchone()

            if not tbl_row:
                # Attempt on-demand schema caching if not pre-indexed
                if self._fetch_and_cache_schema(normalized_name):
                    cur.execute("SELECT name, description, category, keys FROM tables WHERE UPPER(name) = ?", (normalized_name,))
                    tbl_row = cur.fetchone()

            if not tbl_row:
                return None

            keys = tbl_row["keys"].split(",") if tbl_row["keys"] else []

            # Fields
            cur.execute("""
                SELECT name, description, data_type, length, decimals, is_key, check_table
                FROM fields WHERE table_name = ?
            """, (tbl_row["name"],))
            field_rows = cur.fetchall()

            if not field_rows:
                # On-demand fetch and cache into SQLite
                if self._fetch_and_cache_schema(tbl_row["name"]):
                    cur.execute("""
                        SELECT name, description, data_type, length, decimals, is_key, check_table
                        FROM fields WHERE table_name = ?
                    """, (tbl_row["name"],))
                    field_rows = cur.fetchall()

            fields: Dict[str, FieldMeta] = {}
            for f in field_rows:
                # Get possible values for this field
                cur.execute("""
                    SELECT val, description FROM possible_values
                    WHERE table_name = ? AND field_name = ?
                """, (tbl_row["name"], f["name"]))
                pv_rows = cur.fetchall()
                possible_values = [PossibleValue(val=p["val"], desc=p["description"] or "") for p in pv_rows]

                fields[f["name"]] = FieldMeta(
                    name=f["name"],
                    description=f["description"] or "",
                    data_type=f["data_type"] or "CHAR",
                    length=f["length"] or 10,
                    decimals=f["decimals"] or 0,
                    is_key=bool(f["is_key"]),
                    check_table=f["check_table"],
                    possible_values=possible_values
                )

            # Foreign keys
            cur.execute("""
                SELECT field, ref_table, ref_field FROM foreign_keys
                WHERE source_table = ?
            """, (tbl_row["name"],))
            fk_rows = cur.fetchall()
            foreign_keys = [
                ForeignKey(field=fk["field"], ref_table=fk["ref_table"], ref_field=fk["ref_field"])
                for fk in fk_rows
            ]

            return TableSchema(
                name=tbl_row["name"],
                description=tbl_row["description"],
                category=tbl_row["category"],
                keys=keys,
                fields=fields,
                foreign_keys=foreign_keys
            )

    def get_foreign_keys(self, table_name: str) -> List[ForeignKey]:
        """Returns outgoing foreign key relationships for a table."""
        tbl = self.get_table(table_name)
        return tbl.foreign_keys if tbl else []

    def get_possible_values(self, table_name: str, field_name: str) -> List[PossibleValue]:
        """Returns allowed domain codes and business meanings for a field."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT val, description FROM possible_values
                WHERE UPPER(table_name) = ? AND UPPER(field_name) = ?
            """, (table_name.strip().upper(), field_name.strip().upper()))
            return [PossibleValue(val=r["val"], desc=r["description"] or "") for r in cur.fetchall()]

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Searches across table names, descriptions, and field names."""
        pattern = f"%{query.strip().upper()}%"
        with self._get_conn() as conn:
            cur = conn.cursor()
            # Match tables
            cur.execute("""
                SELECT name, description, category FROM tables
                WHERE UPPER(name) LIKE ? OR UPPER(description) LIKE ?
            """, (pattern, pattern))
            tbl_results = [
                {"type": "table", "name": r["name"], "description": r["description"], "category": r["category"]}
                for r in cur.fetchall()
            ]

            # Match fields
            cur.execute("""
                SELECT table_name, name, description, data_type FROM fields
                WHERE UPPER(name) LIKE ? OR UPPER(description) LIKE ?
                LIMIT 20
            """, (pattern, pattern))
            field_results = [
                {"type": "field", "table": r["table_name"], "name": r["name"], "description": r["description"], "data_type": r["data_type"]}
                for r in cur.fetchall()
            ]

            return tbl_results + field_results

    def _fetch_and_cache_schema(self, table_name: str) -> bool:
        """Fetches detailed schema on-demand from LeanX and caches it into SQLite."""
        import re
        import httpx
        from bs4 import BeautifulSoup

        try:
            url = f"https://leanx.eu/sap/table/{table_name}/"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            }
            r = httpx.get(url, headers=headers, follow_redirects=True, timeout=10)
            if r.status_code != 200:
                return False

            soup = BeautifulSoup(r.text, "html.parser")
            main_table = None
            for t in soup.find_all("table"):
                if t.get("class") == ["w-full"]:
                    main_table = t
                    break
            if not main_table and soup.find_all("table"):
                main_table = soup.find_all("table")[0]
            if not main_table:
                return False

            tbody = main_table.find("tbody") or main_table
            rows = tbody.find_all("tr", recursive=False)
            fields = []
            keys = []
            foreign_keys = []

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

                check_table = ""
                if len(tds) > 5:
                    check_table = tds[5].text.strip().upper()
                    if check_table and check_table != "-" and check_table != "NONE":
                        foreign_keys.append((table_name, f_name, check_table, f_name))

                fields.append((table_name, f_name, f_desc, f_type or "CHAR", length, decimals, is_key, check_table))

            if not fields:
                return False

            with self._get_conn() as conn:
                cur = conn.cursor()
                p = table_name[:2]
                cat = "Enterprise"
                if p in ("BK", "BS", "SK", "TC"):
                    cat = "Finance"
                elif p in ("VB", "KN", "LI", "VT"):
                    cat = "Sales & Logistics"
                elif p in ("MA", "LF", "T0"):
                    cat = "Materials & Master Data"
                elif p in ("EK", "EB"):
                    cat = "Procurement"
                elif p in ("AU", "AF"):
                    cat = "Production"
                elif p in ("PA", "HR"):
                    cat = "HR / HCM"
                elif p in ("CO", "CS"):
                    cat = "Controlling"

                cur.execute("""
                    INSERT OR REPLACE INTO tables (name, description, category, keys)
                    VALUES (?, ?, ?, ?)
                """, (table_name, f"SAP Table {table_name}", cat, ",".join(keys) if keys else "MANDT"))
                for f in fields:
                    cur.execute("""
                        INSERT OR REPLACE INTO fields (table_name, name, description, data_type, length, decimals, is_key, check_table)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, f)
                for fk in foreign_keys:
                    cur.execute("""
                        INSERT INTO foreign_keys (source_table, field, ref_table, ref_field)
                        VALUES (?, ?, ?, ?)
                    """, fk)
                conn.commit()
            return True
        except Exception:
            return False
