import random
import re
from typing import Dict, Any, Optional, List
import numpy as np
import pandas as pd
from faker import Faker
from ..catalog.sap_catalog import SAPCatalogManager
from ..catalog.schema_models import TableSchema, FieldMeta
from .rules import FieldRule

# Precompiled date regex for ultra-fast SAP date identification
SAP_DATE_REGEX = re.compile(
    r"(?:_DAT$|_DATE$|^[A-Z0-9]{0,3}DAT[A-Z0-9]?$|^[A-Z0-9]{0,3}DT$|ERDAT|AEDAT|BLDAT|BUDAT|WADAT|FKDAT|AUDAT|BEDAT|CPUDT)"
)

# Candidate header identifier columns to cascade across relational tables
HEADER_KEY_CANDIDATES = frozenset({
    "MANDT", "BUKRS", "BELNR", "GJAHR", "VBELN", "EBELN", "TKNUM",
    "MBLNR", "AUFNR", "KUNNR", "LIFNR", "ID", "ORDER_ID", "DOC_ID", "HEADER_ID"
})

# Protected line-item columns that must never be overwritten by parent header columns
PROTECTED_ITEM_COLS = frozenset({
    "NETWR", "WRBTR", "DMBTR", "MENGE", "KWMENG", "LFIMG", "POSNR", "BUZEI",
    "EBELP", "ZEILE", "MATNR", "ARKTX", "WERKS", "LGORT", "SHKZG", "ERDAT", "AEDAT",
    "STATUS", "DESCRIPTION", "DESC", "COMMENT", "COMMENTS", "NOTE", "NOTES",
    "PRICE", "UNIT_PRICE", "TOTAL", "LINE_TOTAL"
})


def sort_specs_topologically(specs_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Topologically sorts table generation specifications so parent/header tables
    are always generated before child line item tables in relational cascades.
    """
    ordered = {}
    remaining = dict(specs_dict)
    max_iters = len(specs_dict) * 2
    iters = 0
    while remaining and iters < max_iters:
        iters += 1
        progress = False
        for t_name, spec in list(remaining.items()):
            parent = getattr(spec, "parent_table", None)
            if not parent or parent in ordered or parent not in specs_dict:
                ordered[t_name] = spec
                del remaining[t_name]
                progress = True
        if not progress:
            for t_name, spec in remaining.items():
                ordered[t_name] = spec
            break
    return ordered


class DataSynthesizer:
    """
    High-speed synthetic data generator.
    Vectorized and optimized for environments with < 4GB RAM.
    """

    def __init__(self, catalog_manager: Optional[SAPCatalogManager] = None, seed: int = 42):
        self.catalog = catalog_manager or SAPCatalogManager()
        self.seed = seed
        self.faker = Faker()
        self.faker.seed_instance(seed)
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)
        # Also seed global generators for any external libraries relying on them
        Faker.seed(seed)
        random.seed(seed)
        np.random.seed(seed)

    def generate_sap_table(
        self,
        table_name: str,
        row_count: int = 100,
        custom_rules: Optional[Dict[str, FieldRule]] = None,
        parent_df: Optional[pd.DataFrame] = None,
        items_per_parent_range: Optional[List[int]] = None
    ) -> pd.DataFrame:
        """
        Synthesizes a standard SAP table or custom entity with strict relational integrity.
        """
        custom_rules = custom_rules or {}
        schema = self.catalog.get_table(table_name)

        if not schema:
            # Resilient dynamic schema generation for custom / unindexed tables
            fields_dict = {}
            if custom_rules:
                for f_name, r in custom_rules.items():
                    rtype = r.rule_type.lower()
                    dtype = "DEC" if rtype == "range" else ("NUMC" if rtype == "sequence" else "CHAR")
                    fields_dict[f_name] = FieldMeta(name=f_name, description=f_name, data_type=dtype, length=35)
            else:
                fields_dict["ID"] = FieldMeta(name="ID", description="Identifier", data_type="CHAR", length=10)

            # If parent_df is provided, ensure candidate key columns from parent are represented in schema
            if parent_df is not None and not parent_df.empty:
                for p_col in parent_df.columns:
                    is_cand = (
                        p_col in HEADER_KEY_CANDIDATES
                        or p_col.endswith("_ID")
                        or p_col.endswith("_NR")
                        or p_col.endswith("_NUM")
                    )
                    if is_cand and p_col not in PROTECTED_ITEM_COLS and p_col not in fields_dict:
                        fields_dict[p_col] = FieldMeta(name=p_col, description=f"Foreign Key {p_col}", data_type="CHAR", length=35)

            schema = TableSchema(
                name=table_name,
                description=f"Entity {table_name}",
                category="Enterprise",
                fields=fields_dict,
                keys=[list(fields_dict.keys())[0]]
            )

        custom_rules = custom_rules or {}
        data = {}

        # 1. Handle Child Table with Parent DataFrame (Relational Cascade)
        if parent_df is not None and not parent_df.empty:
            return self._generate_child_table(
                table_name, schema, parent_df, custom_rules, items_per_parent_range=items_per_parent_range
            )

        # 2. Standalone or Parent Table Generation
        for field_name, f_meta in schema.fields.items():
            if field_name in custom_rules:
                rule = custom_rules[field_name]
                data[field_name] = self._generate_from_rule(rule, row_count, f_meta)
            else:
                data[field_name] = self._generate_default_field(table_name, field_name, f_meta, row_count)

        df = pd.DataFrame(data)
        return df

    def _generate_child_table(
        self,
        table_name: str,
        schema: TableSchema,
        parent_df: pd.DataFrame,
        custom_rules: Dict[str, FieldRule],
        items_per_parent_range: Optional[List[int]] = None
    ) -> pd.DataFrame:
        """
        Fast vectorized generation of child line items linked to parent records.
        """
        is_bseg = table_name.upper() == "BSEG"
        is_vbap = table_name.upper() == "VBAP"
        is_ekpo = table_name.upper() == "EKPO"
        is_lips = table_name.upper() == "LIPS"
        is_vbrp = table_name.upper() == "VBRP"

        # Fast vectorized parent-to-child item allocation using numpy
        if items_per_parent_range and len(items_per_parent_range) == 2:
            min_items, max_items = items_per_parent_range
            if is_bseg:
                # Guarantee >= 2 items per document for double-entry balancing
                min_items = max(2, min_items)
                max_items = max(min_items, max_items)
            items_per_parent = self.np_rng.integers(min_items, max_items + 1, size=len(parent_df))
        elif is_bseg:
            # For BSEG accounting line items, guarantee >= 2 items per document for double-entry balancing
            items_per_parent = self.np_rng.choice([2, 4], size=len(parent_df))
        else:
            items_per_parent = self.np_rng.integers(1, 5, size=len(parent_df))

        parent_indices = np.repeat(np.arange(len(parent_df)), items_per_parent)
        line_numbers = np.concatenate([np.arange(1, k + 1) for k in items_per_parent])

        total_child_rows = len(parent_indices)
        if total_child_rows == 0:
            return pd.DataFrame(columns=list(schema.fields.keys()))

        # Vectorized generate all child fields
        child_data = {}
        for field_name, f_meta in schema.fields.items():
            if field_name in custom_rules:
                child_data[field_name] = self._generate_from_rule(
                    custom_rules[field_name], total_child_rows, f_meta
                )
            else:
                child_data[field_name] = self._generate_default_field(
                    table_name, field_name, f_meta, total_child_rows
                )

        child_df = pd.DataFrame(child_data)

        # Fast vectorized copy of parent keys
        parent_subset = parent_df.iloc[parent_indices].reset_index(drop=True)

        if is_bseg:
            for k in ["MANDT", "BUKRS", "BELNR", "GJAHR"]:
                if k in parent_subset.columns:
                    child_df[k] = parent_subset[k]
            child_df["BUZEI"] = [f"{idx:03d}" for idx in line_numbers]
            child_df["SHKZG"] = ["S" if idx % 2 == 1 else "H" for idx in line_numbers]

            # DEF-13: Balanced double-entry accounting per document
            # Guarantees sum(Debit 'S') == sum(Credit 'H') per BELNR (O(N) slice-vectorized)
            if "WRBTR" in child_df.columns:
                wrbtr_arr = child_df["WRBTR"].to_numpy(copy=True)
                starts = np.zeros(len(items_per_parent) + 1, dtype=int)
                starts[1:] = np.cumsum(items_per_parent)

                for p_idx in range(len(parent_df)):
                    s_idx = starts[p_idx]
                    e_idx = starts[p_idx + 1]
                    if e_idx - s_idx >= 2:
                        s_offsets = list(range(s_idx, e_idx, 2))
                        h_offsets = list(range(s_idx + 1, e_idx, 2))
                        if s_offsets and h_offsets:
                            s_sum = round(float(np.sum(wrbtr_arr[s_offsets])), 2)
                            h_base = round(s_sum / len(h_offsets), 2)
                            for h_i in h_offsets[:-1]:
                                wrbtr_arr[h_i] = h_base
                            wrbtr_arr[h_offsets[-1]] = round(s_sum - (h_base * (len(h_offsets) - 1)), 2)

                child_df["WRBTR"] = wrbtr_arr
                if "DMBTR" in child_df.columns:
                    child_df["DMBTR"] = wrbtr_arr
        elif is_vbap:
            for k in ["MANDT", "VBELN"]:
                if k in parent_subset.columns:
                    child_df[k] = parent_subset[k]
            child_df["POSNR"] = [f"{idx * 10:06d}" for idx in line_numbers]
            if "NETPR" in child_df.columns and "KWMENG" in child_df.columns:
                try:
                    kw = pd.to_numeric(child_df["KWMENG"], errors="coerce").fillna(10.0)
                    pr = pd.to_numeric(child_df["NETPR"], errors="coerce").fillna(50.0)
                    child_df["NETWR"] = np.round(kw * pr, 2)
                except (ValueError, TypeError, KeyError):
                    pass
        elif is_ekpo:
            for k in ["MANDT", "EBELN"]:
                if k in parent_subset.columns:
                    child_df[k] = parent_subset[k]
            child_df["EBELP"] = [f"{idx * 10:05d}" for idx in line_numbers]
            if "NETPR" in child_df.columns and "MENGE" in child_df.columns:
                try:
                    mg = pd.to_numeric(child_df["MENGE"], errors="coerce").fillna(10.0)
                    pr = pd.to_numeric(child_df["NETPR"], errors="coerce").fillna(50.0)
                    child_df["NETWR"] = np.round(mg * pr, 2)
                except (ValueError, TypeError, KeyError):
                    pass
        elif is_lips or is_vbrp:
            for k in ["MANDT", "VBELN"]:
                if k in parent_subset.columns:
                    child_df[k] = parent_subset[k]
            child_df["POSNR"] = [f"{idx * 10:06d}" for idx in line_numbers]
        else:
            # Foreign-key-aware cascade (DEF-05 & DEF-16: only cascade legitimate identifiers)
            if schema.foreign_keys:
                for fk in schema.foreign_keys:
                    if fk.ref_field in parent_subset.columns and fk.field in child_df.columns:
                        child_df[fk.field] = parent_subset[fk.ref_field]

            for col in parent_subset.columns:
                is_candidate_key = (
                    col in HEADER_KEY_CANDIDATES
                    or col.endswith("_ID")
                    or col.endswith("_NR")
                    or col.endswith("_NUM")
                )
                if col in child_df.columns and col not in PROTECTED_ITEM_COLS and is_candidate_key:
                    child_df[col] = parent_subset[col]

            # Automatically assign standard line item numbers if child has item field
            for item_col in ("POSNR", "BUZEI", "EBELP", "ZEILE", "TPNUM", "BNFPO", "LINE_ID", "ITEM_ID", "ITEM_NUM"):
                if item_col in child_df.columns:
                    step = 10 if item_col in ("POSNR", "EBELP", "BNFPO") else 1
                    pad = schema.fields[item_col].length if (schema.fields and item_col in schema.fields and hasattr(schema.fields[item_col], "length")) else 6
                    child_df[item_col] = [f"{idx * step:0{pad}d}" for idx in line_numbers]
                    break

        return child_df

    def _generate_default_field(
        self,
        table_name: str,
        field_name: str,
        f_meta: Any,
        row_count: int
    ) -> np.ndarray:
        """Vectorized generation of a field based on SAP data type and catalog enums."""
        dtype = f_meta.data_type.upper()
        length = f_meta.length

        # 1. Has predefined possible values
        if f_meta.possible_values:
            val_choices = [pv.val for pv in f_meta.possible_values if pv.val]
            if val_choices:
                return self.np_rng.choice(val_choices, size=row_count)

        # 2. Specific SAP Technical Key & Domain Fields
        if field_name == "MANDT":
            return np.full(row_count, "100")
        elif field_name == "BUKRS":
            return self.np_rng.choice(["1000", "1010", "2000", "3000"], size=row_count)
        elif field_name == "WERKS":
            return self.np_rng.choice(["1000", "1100", "2000", "3000"], size=row_count)
        elif field_name == "LGORT":
            return self.np_rng.choice(["0001", "0002", "0010", "FG01"], size=row_count)
        elif field_name == "VKORG":
            return self.np_rng.choice(["1000", "2000", "3000"], size=row_count)
        elif field_name == "VTWEG":
            return self.np_rng.choice(["10", "20"], size=row_count)
        elif field_name == "SPART":
            return self.np_rng.choice(["00", "01"], size=row_count)
        elif field_name == "EKORG":
            return self.np_rng.choice(["1000", "2000"], size=row_count)
        elif field_name == "EKGRP":
            return self.np_rng.choice(["001", "002", "003"], size=row_count)
        elif field_name == "VKBUR":
            return self.np_rng.choice(["1000", "1100", "2000", "2100"], size=row_count)
        elif field_name == "VKGRP":
            return self.np_rng.choice(["001", "002", "003", "010"], size=row_count)
        elif field_name == "KKBER":
            return self.np_rng.choice(["1000", "2000"], size=row_count)

        # 3. Logistics, Shipping & Trade (Incoterms, Routes, Districts, Unloading Points)
        elif field_name == "INCO1":
            return self.np_rng.choice(["FOB", "CIF", "EXW", "DDP", "CFR", "CIP", "DAP"], size=row_count)
        elif field_name == "INCO2":
            inco_locations = ["Hamburg Port", "Frankfurt", "Rotterdam Port", "New York Pier 4", "Chicago Hub", "Antwerp Harbor"]
            return self.np_rng.choice([loc[:length] for loc in inco_locations], size=row_count)
        elif field_name == "BZIRK":
            return self.np_rng.choice(["000001", "000002", "000003", "US0001", "DE0001"], size=row_count)
        elif field_name in ("ABLAD", "ABLAT"):
            unloading_points = ["Dock 1 - North Ramp", "Warehouse Gate B", "Receiving Bay 3", "Logistics Terminal A", "Silo Bay 4"]
            return self.np_rng.choice([up[:length] for up in unloading_points], size=row_count)
        elif field_name in ("VSTEL", "VSTEL_BEZ"):
            return self.np_rng.choice(["1000", "1100", "2000", "2100"], size=row_count)
        elif field_name in ("ROUTE", "ROUTA"):
            return self.np_rng.choice(["NORTH1", "SOUTH1", "TRANS1", "EUR001", "SEA001"], size=row_count)
        elif field_name in ("TRAGR", "LGTOR"):
            return self.np_rng.choice(["0001", "0002", "0003", "D001", "D002"], size=row_count)
        elif field_name in ("LGNUM", "BEROT"):
            return self.np_rng.choice(["001", "010", "100", "W01"], size=row_count)
        elif field_name == "LPRIO":
            return self.np_rng.choice(["01", "02", "03"], size=row_count)
        elif field_name == "VSBED":
            return self.np_rng.choice(["01", "02", "10"], size=row_count)
        elif field_name == "BOLNR":
            return np.array([f"BOL-{self.rng.randint(1000000, 9999999)}"[:length] for _ in range(row_count)])
        elif field_name == "TRAID":
            return np.array([f"CONT-{self.rng.randint(1000, 9999)}"[:length] for _ in range(row_count)])
        elif field_name in ("AUTLF", "KZAZU"):
            return self.np_rng.choice([" ", "X"], size=row_count, p=[0.7, 0.3])
        elif field_name in ("LIFSK", "FAKSP"):
            return self.np_rng.choice([" ", "01", "02"], size=row_count, p=[0.85, 0.1, 0.05])

        # 4. Material Numbers (MATNR) - Standard 18-digit SAP ALPHA format
        elif field_name == "MATNR":
            mat_pool = [f"{100000 + i:0{min(length, 18)}d}" for i in range(30)]
            return self.np_rng.choice(mat_pool, size=row_count)

        # 5. Customer / Vendor / Partner Technical IDs
        elif any(field_name.startswith(p) for p in ("KUN", "LIF")) or field_name in ("EMPFG", "KNKLI", "PARNR", "KUNAG", "KUNWE", "KUNRE", "KUNRG", "KUNIV", "LIFRE"):
            id_len = min(length, 10)
            return np.array([f"{self.rng.randint(100000, 999999):0{id_len}d}" for _ in range(row_count)])

        # 6. Document Numbers & References
        elif any(field_name.endswith(s) for s in ("BELN", "ELN", "BLNR", "UFNR", "KNUM", "ANFN", "GBEL", "XNUM", "NUMV", "NUMH")) or field_name in ("BELNR", "VBELN", "EBELN", "MBLNR", "AUFNR", "TKNUM", "BANFN", "VGBEL", "EXNUM", "KNUMV"):
            start_num = 10000000
            num_len = min(length, 10)
            nums = np.arange(start_num, start_num + row_count)
            return np.array([f"{n:0{num_len}d}" for n in nums])

        # 7. Line Item Numbers
        elif field_name in ("POSNR", "EBELP", "BNFPO"):
            return np.array([f"{((i % 5) + 1) * 10:0{length}d}" for i in range(row_count)])
        elif field_name in ("BUZEI", "TPNUM", "ZEILE"):
            return np.array([f"{((i % 5) + 1):0{length}d}" for i in range(row_count)])

        # 8. Dates: Strict SAP date fields (prevent substring collisions like MANDAT, DATA, CANDIDATE) (DEF-09)
        elif ((dtype == "DATS" or bool(SAP_DATE_REGEX.search(field_name)))
              and field_name not in ("MANDAT", "DATA", "CANDIDATE", "METADATA", "STAT")):
            days_offset = self.np_rng.integers(0, 90, size=row_count)
            base_dt = np.datetime64("today")
            dates = base_dt - days_offset.astype("timedelta64[D]")
            return np.char.replace(dates.astype("U10"), "-", "")

        # 9. Times: Universal match for ANY SAP time field
        elif "ZET" in field_name or "TIM" in field_name or "UHR" in field_name or field_name.endswith("TM") or dtype == "TIMS":
            hours = self.np_rng.integers(8, 18, size=row_count)
            mins = self.np_rng.integers(0, 60, size=row_count)
            secs = self.np_rng.integers(0, 60, size=row_count)
            return np.array([f"{h:02d}{m:02d}{s:02d}" for h, m, s in zip(hours, mins, secs)])

        # 10. Statuses & Processing Confirmation Codes
        elif field_name in ("KOSTK", "WBSTK", "FKSTK", "GBSTK", "UVALL", "UVALS", "UVFAK", "UVVLK", "PKSTK", "BSTAT", "BESTQ", "KZVBR"):
            return self.np_rng.choice(["A", "B", "C"], size=row_count, p=[0.5, 0.3, 0.2])

        # 11. Currencies, Units of Measure, Languages
        elif field_name in ("WAERS", "WAERK", "HWAER") or dtype == "CUKY":
            return self.np_rng.choice(["EUR", "USD", "GBP"], size=row_count, p=[0.6, 0.3, 0.1])
        elif field_name in ("MEINS", "VRKME", "GEWEI", "VOLEH") or dtype == "UNIT":
            units = [u[:length] for u in ["PC", "KG", "M", "L", "ST"]]
            return self.np_rng.choice(units, size=row_count, p=[0.4, 0.25, 0.15, 0.1, 0.1])
        elif field_name in ("SPRAS", "LANG") or dtype == "LANG":
            langs = [l[:length] for l in ["E", "D", "F", "ES"]]
            return self.np_rng.choice(langs, size=row_count, p=[0.7, 0.15, 0.1, 0.05])

        # 12. Document & Posting Types
        elif field_name == "AUART":
            return self.np_rng.choice(["OR", "ZOR", "QT", "RE"], size=row_count, p=[0.7, 0.15, 0.1, 0.05])
        elif field_name == "BLART":
            return self.np_rng.choice(["KR", "SA", "KZ", "DR", "DZ"], size=row_count, p=[0.4, 0.3, 0.1, 0.1, 0.1])
        elif field_name == "BSART":
            return self.np_rng.choice(["NB", "UB", "FO"], size=row_count, p=[0.8, 0.15, 0.05])
        elif field_name == "LFART":
            return self.np_rng.choice(["LF", "LR", "NL"], size=row_count)
        elif field_name == "FKART":
            return self.np_rng.choice(["F2", "RE", "S1"], size=row_count)
        elif field_name == "BSCHL":
            return self.np_rng.choice(["01", "11", "40", "50"], size=row_count)
        elif field_name == "KOART":
            return self.np_rng.choice(["S", "D", "K"], size=row_count, p=[0.5, 0.3, 0.2])
        elif field_name == "SHKZG":
            return self.np_rng.choice(["S", "H"], size=row_count, p=[0.6, 0.4])
        elif field_name == "MWSKZ":
            return self.np_rng.choice(["V1", "V2", "A1", "A2", "I0"], size=row_count, p=[0.5, 0.2, 0.15, 0.1, 0.05])
        elif field_name == "ZLSPR":
            return self.np_rng.choice([" ", "A", "B"], size=row_count, p=[0.88, 0.1, 0.02])
        elif field_name == "ZLSCH":
            return self.np_rng.choice(["T", "C", "U", "E"], size=row_count, p=[0.5, 0.3, 0.1, 0.1])
        elif field_name == "ZTERM":
            return self.np_rng.choice(["0001", "0002", "NT30", "PT60"], size=row_count)
        elif field_name in ("USNAM", "ERNAM", "AENAM"):
            return self.np_rng.choice(["SYS_BATCH", "CONSULTANT_A", "FIN_ADMIN", "SAP_USER"], size=row_count)
        elif field_name == "GJAHR":
            return self.np_rng.choice(["2024", "2025", "2026"], size=row_count)

        # 13. Financial Amounts & Quantities
        elif dtype in ("CURR", "DEC", "QUAN") or any(field_name.startswith(p) for p in ("WRB", "DMB", "NET", "MEN", "LFM", "LGM", "KWM", "FKI", "BRG", "NTG", "VOL")):
            amounts = self.np_rng.lognormal(mean=5.5, sigma=1.0, size=row_count)
            return np.round(amounts, 2)
        elif dtype in ("INT1", "INT2", "INT4", "INT8"):
            return self.np_rng.integers(1, 100, size=row_count)
        elif dtype == "FLTP":
            return np.round(self.np_rng.uniform(1.0, 1000.0, size=row_count), 4)

        # 14. Boolean / Single Character Flags
        elif length == 1:
            return self.np_rng.choice([" ", "X"], size=row_count, p=[0.85, 0.15])

        # 15. Names, Addresses, Descriptions
        elif any(kw in field_name for kw in ("NAME", "SORTL")):
            return np.array([f"{self.faker.company()}"[:length] for _ in range(row_count)])
        elif any(kw in field_name for kw in ("CITY", "ORT01", "ORT02")):
            return np.array([self.faker.city()[:length] for _ in range(row_count)])
        elif any(kw in field_name for kw in ("STRAS", "STREET")):
            return np.array([self.faker.street_address()[:length] for _ in range(row_count)])
        elif any(kw in field_name for kw in ("PSTLZ", "POST_CODE")):
            return np.array([f"{self.rng.randint(10000, 99999)}"[:length] for _ in range(row_count)])
        elif field_name in ("LAND1", "COUNTRY"):
            countries = [c[:length] for c in ["DE", "US", "FR", "GB", "NL"]]
            return self.np_rng.choice(countries, size=row_count)
        elif field_name in ("REGIO", "STATE"):
            regions = [r[:length] for r in ["01", "08", "CA", "NY", "TX", "BY"]]
            return self.np_rng.choice(regions, size=row_count)
        elif any(kw in field_name for kw in ("TEXT", "DESC", "BEZEI", "ARKTX", "MAKTX")):
            sample_descs = [
                "Standard Industrial Assembly", "Heavy Duty Roller Bearing",
                "High Precision Coupling", "Electronic Sensor Board",
                "Reinforced Rubber Gasket", "Hex Head Flange Bolt M10",
                "Hydraulic Control Valve", "Modular Steel Frame"
            ]
            return self.np_rng.choice([d[:length] for d in sample_descs], size=row_count)

        # 16. Intelligent Zero-VAL Fallback based on Length & Datatype
        elif dtype == "NUMC":
            max_val = min(10**length - 1, 99999999)
            return np.array([f"{self.rng.randint(1, max_val):0{length}d}" for _ in range(row_count)])
        elif length == 2:
            return self.np_rng.choice(["01", "02", "10", "20", "AA", "BB"], size=row_count)
        elif length == 3:
            return self.np_rng.choice(["A01", "B02", "C10", "100", "200"], size=row_count)
        elif length == 4:
            return self.np_rng.choice(["1000", "2000", "3000", "STD1", "GEN1"], size=row_count)
        else:
            # Clean enterprise code
            return self.np_rng.choice([f"STD_{100 + i}"[:length] for i in range(10)], size=row_count)

    def _generate_from_rule(self, rule: FieldRule, row_count: int, f_meta: Any) -> np.ndarray:
        """Executes a custom rule across N rows."""
        rtype = rule.rule_type.lower()
        p = rule.parameters

        if rtype == "choice":
            choices = p.get("choices") or p.get("values") or ["STD_1", "STD_2"]
            weights = p.get("weights")
            if weights and len(weights) == len(choices):
                w_arr = np.array(weights, dtype=float)
                w_sum = w_arr.sum()
                if w_sum > 0:
                    w_arr = w_arr / w_sum
                    return self.np_rng.choice(choices, size=row_count, p=w_arr)
            return self.np_rng.choice(choices, size=row_count)
        elif rtype == "range":
            min_v = p.get("min", 1.0)
            max_v = p.get("max", 1000.0)
            decimals = p.get("decimals", 2)
            vals = self.np_rng.uniform(min_v, max_v, size=row_count)
            return np.round(vals, decimals) if decimals > 0 else np.round(vals).astype(int)
        elif rtype == "fixed":
            return np.full(row_count, p.get("value", ""))
        elif rtype == "sequence":
            prefix = str(p.get("prefix", "")).strip()
            start = int(p.get("start", 10000000))
            step = int(p.get("step", 1))
            pad = int(p.get("pad", 10))

            nums = np.arange(start, start + row_count * step, step)[:row_count]
            if prefix:
                if pad > len(prefix):
                    num_pad = pad - len(prefix)
                    return np.array([f"{prefix}{n:0{num_pad}d}" for n in nums])
                else:
                    return np.array([f"{prefix}{n}" for n in nums])
            else:
                return np.array([f"{n:0{pad}d}" for n in nums])
        elif rtype == "faker":
            provider = p.get("provider", "company").lower()
            # Dynamic scaling up to 5,000 unique items to preserve cardinality at scale (DEF-11)
            pool_size = min(5000, max(250, int(row_count * 0.5))) if row_count > 250 else row_count
            if "comp" in provider:
                pool = [self.faker.company() for _ in range(pool_size)]
            elif "city" in provider:
                pool = [self.faker.city() for _ in range(pool_size)]
            elif "street" in provider or "addr" in provider:
                pool = [self.faker.street_address() for _ in range(pool_size)]
            elif "email" in provider:
                pool = [self.faker.email() for _ in range(pool_size)]
            elif "name" in provider:
                pool = [self.faker.name() for _ in range(pool_size)]
            elif "phone" in provider:
                pool = [self.faker.phone_number() for _ in range(pool_size)]
            else:
                pool = [self.faker.word() for _ in range(pool_size)]

            return self.np_rng.choice(pool, size=row_count) if row_count > pool_size else np.array(pool[:row_count])
        else:
            return self._generate_default_field("", rule.field_name, f_meta, row_count)

    def generate_relational_pair(
        self,
        parent_table: str,
        child_table: str,
        parent_count: int = 100,
        custom_rules: Optional[Dict[str, Dict[str, FieldRule]]] = None,
        items_per_parent_range: Optional[List[int]] = None
    ) -> Dict[str, pd.DataFrame]:
        """
        Generates a complete relational pair (e.g. BKPF + BSEG or VBAK + VBAP)
        with 100% referential join integrity.
        """
        custom_rules = custom_rules or {}
        parent_df = self.generate_sap_table(
            parent_table,
            row_count=parent_count,
            custom_rules=custom_rules.get(parent_table)
        )
        child_df = self.generate_sap_table(
            child_table,
            custom_rules=custom_rules.get(child_table),
            parent_df=parent_df,
            items_per_parent_range=items_per_parent_range
        )
        return {parent_table: parent_df, child_table: child_df}

    def generate_enterprise_flow(
        self,
        config: Optional[Any] = None,
        num_orders: int = 1000,
        num_customers: int = 100,
        num_materials: int = 25,
        num_carriers: int = 10,
        disruption_rate: float = 0.12,
        seed: Optional[int] = None
    ) -> Dict[str, pd.DataFrame]:
        """
        Generates a complete enterprise Order-to-Cash (O2C) and FI/CO lifecycle
        adhering to all 6 Invariant Axioms:
        - Master Referential Closure (KNA1, KNVV, MARA, LFA1)
        - Arrow-of-Time Chronological Sequencing (VBAK, VBAP, LIKP, LIPS, VTTK, VTTP, VBRK, VBRP, BKPF, BSEG)
        - Mathematical Line-to-Header Reconciliation
        - Process Document Flow Reference Preservation
        - Geographic & Multimodal Routing Realism
        - Statistical Pareto & Controlled Disruption Distributions
        """
        from .enterprise_flow import EnterpriseFlowSynthesizer, EnterpriseFlowConfig

        if config is None:
            config = EnterpriseFlowConfig(
                num_customers=num_customers,
                num_materials=num_materials,
                num_carriers=num_carriers,
                num_orders=num_orders,
                disruption_rate=disruption_rate,
                seed=seed if seed is not None else self.seed
            )
        flow_synthesizer = EnterpriseFlowSynthesizer(config)
        return flow_synthesizer.generate_all()
