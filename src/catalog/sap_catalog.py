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
        """Loads complete TableSchema including fields, primary keys, and foreign keys (100% offline)."""
        normalized_name = table_name.strip().upper()
        with self._get_conn() as conn:
            cur = conn.cursor()
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

            # Batch query: Fetch all possible values for this table in a single query (resolves N+1 query issue DEF-10)
            cur.execute("""
                SELECT field_name, val, description FROM possible_values
                WHERE table_name = ?
            """, (tbl_row["name"],))
            pv_by_field: Dict[str, List[PossibleValue]] = {}
            for p in cur.fetchall():
                fname = p["field_name"]
                if fname not in pv_by_field:
                    pv_by_field[fname] = []
                pv_by_field[fname].append(PossibleValue(val=p["val"], desc=p["description"] or ""))

            fields: Dict[str, FieldMeta] = {}
            for f in field_rows:
                possible_values = pv_by_field.get(f["name"], [])
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

