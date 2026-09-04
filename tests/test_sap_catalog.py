"""
Unit tests for the Offline SAP Reference Catalog.
"""
import pytest
from src.catalog.sap_catalog import SAPCatalogManager


@pytest.fixture
def catalog():
    return SAPCatalogManager()


def test_core_tables_exist(catalog):
    tables = catalog.list_tables()
    table_names = {t["name"] for t in tables}
    expected = {"BKPF", "BSEG", "VBAK", "VBAP", "KNA1", "LFA1", "MARA", "T001", "T003", "TCURC"}
    assert expected.issubset(table_names), f"Missing core tables: {expected - table_names}"


def test_bkpf_schema_and_keys(catalog):
    bkpf = catalog.get_table("BKPF")
    assert bkpf is not None
    assert bkpf.name == "BKPF"
    assert "Accounting Document Header" in bkpf.description
    assert set(bkpf.keys) == {"MANDT", "BUKRS", "BELNR", "GJAHR"}
    
    # Check key fields
    assert "BUKRS" in bkpf.fields
    assert bkpf.fields["BUKRS"].length == 4
    assert bkpf.fields["BELNR"].length == 10


def test_bseg_foreign_keys_to_bkpf(catalog):
    bseg = catalog.get_table("BSEG")
    assert bseg is not None
    fk_refs = {(fk.field, fk.ref_table, fk.ref_field) for fk in bseg.foreign_keys}
    
    # Must contain links to BKPF
    assert ("BELNR", "BKPF", "BELNR") in fk_refs
    assert ("BUKRS", "BKPF", "BUKRS") in fk_refs
    assert ("GJAHR", "BKPF", "GJAHR") in fk_refs


def test_possible_values_lookup(catalog):
    vals = catalog.get_possible_values("BKPF", "BLART")
    val_codes = {v.val for v in vals}
    assert "KR" in val_codes  # Vendor invoice
    assert "SA" in val_codes  # G/L account document


def test_catalog_search(catalog):
    results = catalog.search("Accounting")
    assert len(results) > 0
    names = [r.get("name") for r in results]
    assert "BKPF" in names or any("Accounting" in str(r.get("description")) for r in results)


def test_zero_third_party_branding(catalog):
    """Verify that neither the SQLite DB nor definitions contain external brand names."""
    with catalog._get_conn() as conn:
        cur = conn.cursor()
        for table in ["tables", "fields", "possible_values", "foreign_keys"]:
            cur.execute(f"SELECT * FROM {table}")
            for row in cur.fetchall():
                row_str = " ".join([str(val) for val in row if val is not None]).lower()
                assert "leanx" not in row_str, f"Forbidden third-party brand found in {table}: {row_str}"
                assert "leanix" not in row_str, f"Forbidden third-party brand found in {table}: {row_str}"
