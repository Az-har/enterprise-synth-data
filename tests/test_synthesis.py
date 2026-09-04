"""
Unit tests for the Vectorized Synthetic Data Generation Engine.
"""
import time
import pytest
from src.synthesis.generator import DataSynthesizer


@pytest.fixture
def synthesizer():
    return DataSynthesizer()


def test_generate_single_sap_table(synthesizer):
    df_bkpf = synthesizer.generate_sap_table("BKPF", row_count=50)
    assert len(df_bkpf) == 50
    assert "BELNR" in df_bkpf.columns
    assert "BUKRS" in df_bkpf.columns
    # Check 10-digit zero-padded BELNR
    assert all(len(str(val)) == 10 for val in df_bkpf["BELNR"])


def test_relational_pair_generation_and_fk_integrity(synthesizer):
    """Generates BKPF and BSEG and verifies 100% referential integrity."""
    start_time = time.time()
    pair = synthesizer.generate_relational_pair(
        parent_table="BKPF",
        child_table="BSEG",
        parent_count=500
    )
    duration = time.time() - start_time

    df_bkpf = pair["BKPF"]
    df_bseg = pair["BSEG"]

    # Speed check: 500 headers + ~1,500 line items generated in < 2 seconds
    assert duration < 2.5, f"Generation took too long: {duration:.2f}s"

    assert len(df_bkpf) == 500
    assert len(df_bseg) >= 500  # Multiple items per header

    # Referential integrity check: every BELNR in BSEG MUST exist in BKPF
    parent_belnrs = set(df_bkpf["BELNR"])
    child_belnrs = set(df_bseg["BELNR"])
    assert child_belnrs.issubset(parent_belnrs), "Foreign key integrity violated: BSEG contains unparented BELNRs!"

    # Line item numbering check (BUZEI starts at 001)
    assert "001" in set(df_bseg["BUZEI"])


def test_vbeln_sequence_and_erzet_time_format(synthesizer):
    """Verifies that sequence rule yields 10-digit IDs and ERZET yields valid HHMMSS time."""
    from src.templates.excel_parser import FaultTolerantExcelParser
    parser = FaultTolerantExcelParser()
    rule = parser._parse_rule_string("VBELN", "sequence", "prefix: 5, start: 100000000, pad: 10")
    
    assert rule.rule_type == "sequence"
    assert rule.parameters["prefix"] == "5"

    df_vbak = synthesizer.generate_sap_table("VBAK", row_count=10, custom_rules={"VBELN": rule})
    
    # 1. VBELN must be 10-digit numeric sequence starting with 5100000000
    vbeln_list = list(df_vbak["VBELN"])
    assert vbeln_list[0] == "5100000000"
    assert vbeln_list[1] == "5100000001"
    assert all(len(v) == 10 for v in vbeln_list)

    # 2. ERZET must be 6-digit valid time format (HHMMSS)
    erzet_list = list(df_vbak["ERZET"])
    for t_val in erzet_list:
        assert len(t_val) == 6, f"ERZET {t_val} is not 6 chars"
        assert t_val.isdigit(), f"ERZET {t_val} is not numeric"
        hh = int(t_val[:2])
        mm = int(t_val[2:4])
        ss = int(t_val[4:])
        assert 0 <= hh < 24 and 0 <= mm < 60 and 0 <= ss < 60, f"Invalid time {t_val}"


def test_likp_and_lips_enterprise_fields_and_zero_val_output(synthesizer):
    """Verifies that LIKP and LIPS generate zero VAL dummy values and valid enterprise fields."""
    df_likp = synthesizer.generate_sap_table("LIKP", row_count=10)
    df_lips = synthesizer.generate_sap_table("LIPS", row_count=10)

    # 1. Zero VAL dummy columns in LIKP (204 cols) and LIPS (369 cols)
    for tbl_name, df in [("LIKP", df_likp), ("LIPS", df_lips)]:
        val_cols = [c for c in df.columns if any(str(v).startswith("VAL") for v in df[c])]
        assert len(val_cols) == 0, f"Table {tbl_name} still contains VAL dummy columns: {val_cols}"

    # 2. Check specific fields mentioned by user
    # BZIRK (Sales District)
    assert "BZIRK" in df_likp.columns
    assert all(len(str(b)) > 0 and not str(b).startswith("VAL") for b in df_likp["BZIRK"])

    # WADAT (Goods Issue Date - DATS YYYYMMDD)
    assert "WADAT" in df_likp.columns
    for d in df_likp["WADAT"]:
        assert len(str(d)) == 8 and str(d).isdigit()

    # ABLAD (Unloading Point)
    assert "ABLAD" in df_likp.columns
    assert all(len(str(a)) > 0 and not str(a).startswith("VAL") for a in df_likp["ABLAD"])

    # INCO1 & INCO2 (Incoterms)
    assert "INCO1" in df_likp.columns
    assert all(str(i) in ["FOB", "CIF", "EXW", "DDP", "CFR", "CIP", "DAP"] for i in df_likp["INCO1"])
    assert "INCO2" in df_likp.columns
    assert all(len(str(i2)) > 0 and not str(i2).startswith("VAL") for i2 in df_likp["INCO2"])

    # MATNR in LIPS (18-digit zero-padded SAP material)
    assert "MATNR" in df_lips.columns
    for m in df_lips["MATNR"]:
        assert len(str(m)) == 18 and str(m).isdigit()

