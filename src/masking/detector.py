"""
Sensitive Column Detector.
Automatically detects PII and confidential enterprise columns based on header semantics and content sampling.
Requires 0 extra memory (rule & regex based).
"""
import re
from typing import Dict, List, Any, Optional
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

# Pre-compiled regular expressions for ultra-fast column header and content scanning
COMPILED_SENSITIVE_PATTERNS = {
    cat: [re.compile(pat) for pat in patterns]
    for cat, patterns in SENSITIVE_PATTERNS.items()
}

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
IBAN_REGEX = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{10,30}$")
VAT_REGEX = re.compile(r"^[A-Z]{2}[0-9]{8,12}$")


class SensitiveColumnDetector:
    """Detects and recommends columns for masking from DataFrames or table schemas."""

    @staticmethod
    def detect_category_from_header(col_name: str) -> Optional[str]:
        """Detects sensitive category strictly from column header name using pre-compiled regexes."""
        col_str = str(col_name).strip().upper()
        for cat, compiled_pats in COMPILED_SENSITIVE_PATTERNS.items():
            if any(pat.search(col_str) for pat in compiled_pats):
                return cat
        return None

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
            detected_cat = self.detect_category_from_header(col_str)
            confidence = "HIGH" if detected_cat else "MEDIUM"

            # 2. If no strong match on header, inspect content samples cell-by-cell (DEF-08: no cross-row bleed)
            if not detected_cat and not sample_df[col].empty:
                non_null_samples = [str(v).strip() for v in sample_df[col].dropna() if str(v).strip()]
                for sample_val_str in non_null_samples[:15]:
                    # Email check
                    if "@" in sample_val_str and EMAIL_REGEX.search(sample_val_str):
                        detected_cat = "email"
                        confidence = "HIGH"
                        break
                    # IBAN check (strip spaces)
                    clean_str = sample_val_str.replace(" ", "").upper()
                    if IBAN_REGEX.search(clean_str):
                        detected_cat = "bank_iban"
                        confidence = "HIGH"
                        break
                    # VAT check (strip spaces)
                    elif VAT_REGEX.search(clean_str):
                        detected_cat = "vat_tax_id"
                        confidence = "HIGH"
                        break

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
