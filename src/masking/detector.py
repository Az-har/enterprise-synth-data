"""
Sensitive Column Detector.
Automatically detects PII and confidential enterprise columns based on header semantics and content sampling.
Requires 0 extra memory (rule & regex based).
"""
import re
from typing import Dict, List, Any
import pandas as pd


# Semantic keyword mapping for column headers
SENSITIVE_PATTERNS = {
    "company_name": [
        r"NAME1", r"NAME2", r"COMPANY", r"VENDOR.*NAME", r"CUST.*NAME",
        r"ORGANIZATION", r"FIRMA", r"BUTXT"
    ],
    "person_name": [
        r"FIRST.*NAME", r"LAST.*NAME", r"SURNAME", r"USNAM", r"EMPLOYEE",
        r"CONTACT", r"FULL.*NAME", r"BENEFICIARY"
    ],
    "vat_tax_id": [
        r"STCEG", r"TAX.*ID", r"VAT", r"TIN", r"EIN", r"STCD1", r"STCD2"
    ],
    "bank_iban": [
        r"BANKN", r"IBAN", r"ACCOUNT.*NUM", r"ROUTING", r"SWIFT", r"BIC"
    ],
    "financial_amount": [
        r"DMBTR", r"WRBTR", r"NETWR", r"SALARY", r"AMOUNT", r"PRICE",
        r"REVENUE", r"BALANCE", r"PAYMENT", r"TOTAL"
    ],
    "email": [
        r"EMAIL", r"MAIL"
    ],
    "phone": [
        r"TELF[0-9]", r"PHONE", r"MOBILE", r"TEL"
    ],
    "address": [
        r"STRAS", r"STREET", r"ADDRESS", r"ORT01", r"CITY", r"PSTLZ", r"ZIP"
    ],
    "id_number": [
        r"KUNNR", r"LIFNR", r"BELNR", r"CUSTOMER.*ID", r"VENDOR.*ID",
        r"DOC.*NUM", r"SSN", r"PASSPORT"
    ]
}


class SensitiveColumnDetector:
    """Detects and recommends columns for masking from DataFrames or table schemas."""

    def analyze_dataframe(self, df: pd.DataFrame, max_samples: int = 50) -> List[Dict[str, Any]]:
        """
        Analyzes a DataFrame and returns suggested columns to mask.
        Returns a list of dicts with:
        - column: str
        - category: str (e.g. company_name, bank_iban, etc.)
        - confidence: str ('HIGH', 'MEDIUM')
        - sample_val: Any
        """
        suggestions = []
        sample_df = df.head(max_samples)

        for col in df.columns:
            col_str = str(col).strip().upper()
            detected_cat = None
            confidence = "MEDIUM"

            # 1. Check header keyword patterns
            for cat, patterns in SENSITIVE_PATTERNS.items():
                if any(re.search(pat, col_str) for pat in patterns):
                    detected_cat = cat
                    confidence = "HIGH"
                    break

            # 2. If no strong match on header, inspect content samples
            if not detected_cat and not sample_df[col].empty:
                non_null_samples = sample_df[col].dropna().astype(str).tolist()
                if non_null_samples:
                    sample_txt = " ".join(non_null_samples[:10])
                    # Email check
                    if "@" in sample_txt and re.search(r"[\w\.-]+@[\w\.-]+\.\w+", sample_txt):
                        detected_cat = "email"
                        confidence = "HIGH"
                    # IBAN check
                    elif re.search(r"\b[A-Z]{2}[0-9]{2}[A-Z0-9]{10,30}\b", sample_txt):
                        detected_cat = "bank_iban"
                        confidence = "HIGH"
                    # VAT check
                    elif re.search(r"\b[A-Z]{2}[0-9]{8,12}\b", sample_txt):
                        detected_cat = "vat_tax_id"
                        confidence = "HIGH"

            if detected_cat:
                sample_val = None
                for v in sample_df[col]:
                    if pd.notna(v) and str(v).strip():
                        sample_val = str(v)
                        break

                suggestions.append({
                    "column": str(col),
                    "category": detected_cat,
                    "confidence": confidence,
                    "sample": sample_val or ""
                })

        return suggestions
