"""
Data Masking Engine.
High-level orchestrator for multi-table, format-preserving, referential data obfuscation.
"""
from typing import Dict, List, Any, Optional
import pandas as pd
from .vault import ReferentialVault
from .format_preserver import FormatPreservingMasker
from .numeric_masker import NumericMasker
from .detector import SensitiveColumnDetector


class DataMaskingEngine:
    """
    Orchestrates format-preserving referential data masking across single or multiple tables.
    """

    def __init__(self, salt: str = "enterprise_synth_salt_2026", seed: int = 42):
        self.vault = ReferentialVault(salt=salt)
        self.format_preserver = FormatPreservingMasker(seed=seed)
        self.numeric_masker = NumericMasker(seed=seed)
        self.detector = SensitiveColumnDetector()

    def detect_sensitive_columns(self, tables: Dict[str, pd.DataFrame]) -> Dict[str, List[Dict[str, Any]]]:
        """Scans all tables and suggests columns to mask."""
        results = {}
        for tbl_name, df in tables.items():
            results[tbl_name] = self.detector.analyze_dataframe(df)
        return results

    def set_custom_replacements(self, domain_or_column: str, values: List[str]):
        """Registers a user-supplied replacement list for a column or domain."""
        self.vault.set_custom_pool(domain_or_column, values)

    def mask_dataset(
        self,
        tables: Dict[str, pd.DataFrame],
        column_configs: Dict[str, Dict[str, str]],
        custom_pools: Optional[Dict[str, List[str]]] = None
    ) -> Dict[str, pd.DataFrame]:
        """
        Masks the specified columns across tables.
        
        column_configs format:
        {
            "TableName": {
                "ColumnName": "category"  # e.g. "company_name", "id_number", "financial_amount", etc.
            }
        }
        """
        if custom_pools:
            for domain, pool in custom_pools.items():
                self.vault.set_custom_pool(domain, pool)

        masked_tables = {}

        for tbl_name, df in tables.items():
            masked_df = df.copy()
            tbl_cfg = column_configs.get(tbl_name, {})

            for col_name, category in tbl_cfg.items():
                if col_name not in masked_df.columns:
                    # Case-insensitive column matching
                    matched_col = None
                    for actual_col in masked_df.columns:
                        if actual_col.strip().upper() == col_name.strip().upper():
                            matched_col = actual_col
                            break
                    if not matched_col:
                        continue
                    target_col = matched_col
                else:
                    target_col = col_name

                # Shared domain for cross-table referential integrity:
                # If column is an ID (e.g. KUNNR, LIFNR, BELNR, CUSTOMER_ID), use normalized column name as domain
                domain_key = target_col.strip().upper() if category in ("id_number", "company_name", "bank_iban") else f"{tbl_name}_{target_col}"

                # High-speed vectorized dictionary mapping over unique values
                unique_vals = [v for v in masked_df[target_col].dropna().unique() if str(v).strip() != ""]
                val_mapping = {v: self._mask_cell(v, category, domain_key) for v in unique_vals}
                masked_df[target_col] = masked_df[target_col].map(lambda v: val_mapping.get(v, v))

            masked_tables[tbl_name] = masked_df

        return masked_tables

    def _mask_cell(self, val: Any, category: str, domain_key: str) -> Any:
        """Applies format-preserving masking to a single cell value via the vault."""
        if pd.isna(val) or str(val).strip() == "":
            return val

        raw_str = str(val).strip()

        if category == "company_name":
            return self.vault.get_or_create(
                domain_key,
                raw_str,
                lambda s: self.format_preserver.mask_company_name(s)
            )
        elif category == "person_name":
            return self.vault.get_or_create(
                domain_key,
                raw_str,
                lambda s: self.format_preserver.mask_person_name(s)
            )
        elif category == "vat_tax_id":
            return self.vault.get_or_create(
                domain_key,
                raw_str,
                lambda s: self.format_preserver.mask_tax_vat_id(s)
            )
        elif category == "bank_iban":
            return self.vault.get_or_create(
                domain_key,
                raw_str,
                lambda s: self.numeric_masker.mask_bank_account(s)
            )
        elif category == "id_number":
            return self.vault.get_or_create(
                domain_key,
                raw_str,
                lambda s: self.numeric_masker.mask_id_string(s)
            )
        elif category == "financial_amount":
            return self.numeric_masker.mask_amount(val)
        elif category == "email":
            return self.vault.get_or_create(
                domain_key,
                raw_str,
                lambda s: self.format_preserver.mask_email(s)
            )
        else:
            # Generic format-preserving fallback
            return self.vault.get_or_create(
                domain_key,
                raw_str,
                lambda s: self.format_preserver.mask_company_name(s)
            )

    def generate_preview(
        self,
        tables: Dict[str, pd.DataFrame],
        column_configs: Dict[str, Dict[str, str]],
        custom_pools: Optional[Dict[str, List[str]]] = None,
        preview_rows: int = 5
    ) -> Dict[str, Dict[str, pd.DataFrame]]:
        # Use an isolated engine instance so 5-row preview never mutates production vault state or advances custom pool counters (DEF-06)
        preview_engine = DataMaskingEngine(salt=self.vault.salt)
        sample_tables = {name: df.head(preview_rows).copy() for name, df in tables.items()}
        masked_samples = preview_engine.mask_dataset(sample_tables, column_configs, custom_pools)
        preview = {}
        for name in tables.keys():
            preview[name] = {
                "original": sample_tables[name],
                "masked": masked_samples[name]
            }
        return preview

