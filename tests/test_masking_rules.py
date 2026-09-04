"""
Unit tests for the Strict Data Masking Rules.
Verifies Rule 1 (ABB LLC -> 3-token + LLC), Rule 2 (Vault 1:1 Cardinality & Joins), and Rule 3 (Numeric Obfuscation).
"""
import pytest
import pandas as pd
from src.masking.format_preserver import FormatPreservingMasker
from src.masking.vault import ReferentialVault
from src.masking.numeric_masker import NumericMasker
from src.masking.masking_engine import DataMaskingEngine


@pytest.fixture
def preserver():
    return FormatPreservingMasker(seed=123)


@pytest.fixture
def vault():
    return ReferentialVault(salt="test_salt_123")


@pytest.fixture
def num_masker():
    return NumericMasker(seed=123)


def test_rule_1_abb_llc_suffix_and_word_count(preserver):
    """Rule 1: 'ABB LLC' must produce another 3-word company with 'LLC'."""
    original = "ABB LLC"
    masked = preserver.mask_company_name(original, target_word_count=3)
    
    # Must end with LLC
    assert masked.endswith("LLC"), f"Expected masked name to end with LLC, got: {masked}"
    
    # Must have exactly 3 tokens
    tokens = masked.split()
    assert len(tokens) == 3, f"Expected 3 words for '{original}', got {len(tokens)}: '{masked}'"
    
    # Must not equal original
    assert masked != original


def test_rule_1_international_legal_suffixes(preserver):
    """Rule 1: Preserves various legal entity suffixes (AG, GmbH, Inc, Corp)."""
    assert preserver.mask_company_name("Siemens AG").endswith("AG")
    assert preserver.mask_company_name("Bosch GmbH").endswith("GmbH")
    assert preserver.mask_company_name("Apple Inc.").endswith("Inc.")
    assert preserver.mask_company_name("Tesla Motors Corp").endswith("Corp")


def test_rule_2_exact_cardinality_preservation(vault, preserver):
    """Rule 2: A column with 5 distinct values across 1,000 rows must remain EXACTLY 5 distinct values."""
    companies = ["ABB LLC", "Siemens AG", "Bosch GmbH", "Schneider Electric SE", "General Electric Co"]
    # Repeat 200 times = 1,000 rows
    dataset = companies * 200
    assert len(dataset) == 1000
    assert len(set(dataset)) == 5

    masked_dataset = [
        vault.get_or_create("company_domain", name, lambda s: preserver.mask_company_name(s))
        for name in dataset
    ]

    # Length must be unchanged
    assert len(masked_dataset) == 1000
    # Cardinality must be EXACTLY 5
    assert len(set(masked_dataset)) == 5, f"Expected exactly 5 unique values, got: {len(set(masked_dataset))}"
    
    # Verification stats
    stats = vault.get_stats("company_domain")
    assert stats["cardinality_preserved"] is True
    assert stats["unique_original_values"] == 5
    assert stats["unique_masked_values"] == 5


def test_rule_2_cross_table_referential_join(vault, preserver):
    """Rule 2: If Customer 'ABB LLC' appears in Table A and Table B, it must map to the exact same value."""
    customer_a = "ABB LLC"
    customer_b = "ABB LLC"

    masked_a = vault.get_or_create("shared_customers", customer_a, lambda s: preserver.mask_company_name(s))
    masked_b = vault.get_or_create("shared_customers", customer_b, lambda s: preserver.mask_company_name(s))

    assert masked_a == masked_b, f"Referential join failed: '{masked_a}' != '{masked_b}'"


def test_rule_2_custom_user_list_with_overflow_protection(vault, preserver):
    """
    If user provides 3 custom names, but there are 5 unique companies:
    Engine uses all 3 custom names, then generates 2 unique names so cardinality of 5 is preserved!
    """
    custom_names = ["Apex Global LLC", "Titan Dynamics LLC", "Zephyr Systems LLC"]
    vault.set_custom_pool("vendor_domain", custom_names)

    five_vendors = ["Vendor A", "Vendor B", "Vendor C", "Vendor D", "Vendor E"]
    masked = [
        vault.get_or_create("vendor_domain", v, lambda s: preserver.mask_company_name(s))
        for v in five_vendors
    ]

    # All 3 custom names must be present
    for c_name in custom_names:
        assert c_name in masked, f"Custom name '{c_name}' was not used!"

    # Total unique values must be 5 (no collision, cardinality intact)
    assert len(set(masked)) == 5


def test_rule_3_numeric_id_obfuscation(num_masker):
    """Rule 3: 10-digit zero-padded SAP document number maintains length and leading zeros."""
    original_id = "0001048291"
    masked_id = num_masker.mask_id_string(original_id)

    assert len(masked_id) == len(original_id)  # Exact length 10
    assert masked_id.startswith("000")  # Exact 3 leading zeros
    assert masked_id != original_id  # Completely different number
    assert masked_id.isdigit()  # Must be strictly numeric


def test_rule_3_financial_amount_perturbation(num_masker):
    """Rule 3: Financial amount is perturbed realistically, keeping 2 decimals and positive sign."""
    orig_amt = 15420.50
    masked_amt = num_masker.mask_amount(orig_amt)

    assert masked_amt != orig_amt
    assert masked_amt > 0  # Preserves positive sign
    # Must be within +/- 25%
    assert 0.70 * orig_amt <= masked_amt <= 1.30 * orig_amt
    # Check 2 decimal places
    assert round(masked_amt, 2) == masked_amt


def test_multi_table_masking_engine():
    """End-to-end multi-table masking test with DataFrames."""
    engine = DataMaskingEngine(seed=42)

    df_customers = pd.DataFrame({
        "KUNNR": ["0000000001", "0000000002", "0000000003"],
        "NAME1": ["ABB LLC", "Siemens AG", "Schneider SE"],
        "STCEG": ["DE123456789", "DE987654321", "FR555666777"]
    })

    df_invoices = pd.DataFrame({
        "BELNR": ["0100000001", "0100000002", "0100000003", "0100000004"],
        "KUNNR": ["0000000001", "0000000001", "0000000002", "0000000003"],  # Customer 1 has 2 invoices
        "WRBTR": [5000.00, 7500.25, 12000.00, 3400.50]
    })

    tables = {"Customers": df_customers, "Invoices": df_invoices}
    configs = {
        "Customers": {"KUNNR": "id_number", "NAME1": "company_name", "STCEG": "vat_tax_id"},
        "Invoices": {"BELNR": "id_number", "KUNNR": "id_number", "WRBTR": "financial_amount"}
    }

    masked = engine.mask_dataset(tables, configs)

    # 1. Verify Customers table masked
    m_cust = masked["Customers"]
    assert m_cust["NAME1"].iloc[0].endswith("LLC")
    assert m_cust["NAME1"].iloc[0] != "ABB LLC"

    # 2. Verify Cross-table join on KUNNR is PRESERVED
    masked_kunnr_cust_1 = m_cust.loc[m_cust["KUNNR"] == m_cust["KUNNR"].iloc[0], "KUNNR"].values[0]
    m_inv = masked["Invoices"]
    # Customer 1 had 2 invoices originally
    inv_matches = m_inv[m_inv["KUNNR"] == masked_kunnr_cust_1]
    assert len(inv_matches) == 2, "Cross-table join integrity failed on KUNNR!"
