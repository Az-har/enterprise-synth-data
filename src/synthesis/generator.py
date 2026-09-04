"""
High-Speed Vectorized Synthetic Data Generator.
Synthesizes relational SAP and Custom datasets with strict constraint and foreign key enforcement.
"""
import random
from typing import Dict, Any, Optional
import numpy as np
import pandas as pd
from faker import Faker
from ..catalog.sap_catalog import SAPCatalogManager
from ..catalog.schema_models import TableSchema, FieldMeta
from .rules import FieldRule


class DataSynthesizer:
    """
    High-speed synthetic data generator.
    Vectorized and optimized for environments with < 4GB RAM.
    """

    def __init__(self, catalog_manager: Optional[SAPCatalogManager] = None, seed: int = 42):
        self.catalog = catalog_manager or SAPCatalogManager()
        self.faker = Faker()
        Faker.seed(seed)
        random.seed(seed)
        np.random.seed(seed)

    def generate_sap_table(
        self,
        table_name: str,
        row_count: int = 100,
        custom_rules: Optional[Dict[str, FieldRule]] = None,
        parent_df: Optional[pd.DataFrame] = None
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
            return self._generate_child_table(table_name, schema, parent_df, custom_rules)

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
        custom_rules: Dict[str, FieldRule]
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
        items_per_parent = np.random.randint(1, 5, size=len(parent_df))
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
        elif is_vbap:
            for k in ["MANDT", "VBELN"]:
                if k in parent_subset.columns:
                    child_df[k] = parent_subset[k]
            child_df["POSNR"] = [f"{idx * 10:06d}" for idx in line_numbers]
        elif is_ekpo:
            for k in ["MANDT", "EBELN"]:
                if k in parent_subset.columns:
                    child_df[k] = parent_subset[k]
            child_df["EBELP"] = [f"{idx * 10:05d}" for idx in line_numbers]
        elif is_lips or is_vbrp:
            for k in ["MANDT", "VBELN"]:
                if k in parent_subset.columns:
                    child_df[k] = parent_subset[k]
            child_df["POSNR"] = [f"{idx * 10:06d}" for idx in line_numbers]
        else:
            # Generic parent key cascade
            for col in parent_subset.columns:
                if col in child_df.columns:
                    child_df[col] = parent_subset[col]

            # Automatically assign standard line item numbers if child has item field
            for item_col in ("POSNR", "BUZEI", "EBELP", "ZEILE", "TPNUM", "BNFPO"):
                if item_col in child_df.columns:
                    step = 10 if item_col in ("POSNR", "EBELP", "BNFPO") else 1
                    pad = schema.fields[item_col].length if item_col in schema.fields else 6
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
                return np.random.choice(val_choices, size=row_count)

        # 2. Specific SAP Technical Key & Domain Fields
        if field_name == "MANDT":
            return np.full(row_count, "100")
        elif field_name == "BUKRS":
            return np.random.choice(["1000", "1010", "2000", "3000"], size=row_count)
        elif field_name == "WERKS":
            return np.random.choice(["1000", "1100", "2000", "3000"], size=row_count)
        elif field_name == "LGORT":
            return np.random.choice(["0001", "0002", "0010", "FG01"], size=row_count)
        elif field_name == "VKORG":
            return np.random.choice(["1000", "2000", "3000"], size=row_count)
        elif field_name == "VTWEG":
            return np.random.choice(["10", "20"], size=row_count)
        elif field_name == "SPART":
            return np.random.choice(["00", "01"], size=row_count)
        elif field_name == "EKORG":
            return np.random.choice(["1000", "2000"], size=row_count)
        elif field_name == "EKGRP":
            return np.random.choice(["001", "002", "003"], size=row_count)
        elif field_name == "VKBUR":
            return np.random.choice(["1000", "1100", "2000", "2100"], size=row_count)
        elif field_name == "VKGRP":
            return np.random.choice(["001", "002", "003", "010"], size=row_count)
        elif field_name == "KKBER":
            return np.random.choice(["1000", "2000"], size=row_count)

        # 3. Logistics, Shipping & Trade (Incoterms, Routes, Districts, Unloading Points)
        elif field_name == "INCO1":
            return np.random.choice(["FOB", "CIF", "EXW", "DDP", "CFR", "CIP", "DAP"], size=row_count)
        elif field_name == "INCO2":
            inco_locations = ["Hamburg Port", "Frankfurt", "Rotterdam Port", "New York Pier 4", "Chicago Hub", "Antwerp Harbor"]
            return np.random.choice([loc[:length] for loc in inco_locations], size=row_count)
        elif field_name == "BZIRK":
            return np.random.choice(["000001", "000002", "000003", "US0001", "DE0001"], size=row_count)
        elif field_name in ("ABLAD", "ABLAT"):
            unloading_points = ["Dock 1 - North Ramp", "Warehouse Gate B", "Receiving Bay 3", "Logistics Terminal A", "Silo Bay 4"]
            return np.random.choice([up[:length] for up in unloading_points], size=row_count)
        elif field_name in ("VSTEL", "VSTEL_BEZ"):
            return np.random.choice(["1000", "1100", "2000", "2100"], size=row_count)
        elif field_name in ("ROUTE", "ROUTA"):
            return np.random.choice(["NORTH1", "SOUTH1", "TRANS1", "EUR001", "SEA001"], size=row_count)
        elif field_name in ("TRAGR", "LGTOR"):
            return np.random.choice(["0001", "0002", "0003", "D001", "D002"], size=row_count)
        elif field_name in ("LGNUM", "BEROT"):
            return np.random.choice(["001", "010", "100", "W01"], size=row_count)
        elif field_name == "LPRIO":
            return np.random.choice(["01", "02", "03"], size=row_count)
        elif field_name == "VSBED":
            return np.random.choice(["01", "02", "10"], size=row_count)
        elif field_name == "BOLNR":
            return np.array([f"BOL-{random.randint(1000000, 9999999)}"[:length] for _ in range(row_count)])
        elif field_name == "TRAID":
            return np.array([f"CONT-{random.randint(1000, 9999)}"[:length] for _ in range(row_count)])
        elif field_name in ("AUTLF", "KZAZU"):
            return np.random.choice([" ", "X"], size=row_count, p=[0.7, 0.3])
        elif field_name in ("LIFSK", "FAKSP"):
            return np.random.choice([" ", "01", "02"], size=row_count, p=[0.85, 0.1, 0.05])

        # 4. Material Numbers (MATNR) - Standard 18-digit SAP ALPHA format
        elif field_name == "MATNR":
            mat_pool = [f"{100000 + i:0{min(length, 18)}d}" for i in range(30)]
            return np.random.choice(mat_pool, size=row_count)

        # 5. Customer / Vendor / Partner Technical IDs
        elif any(field_name.startswith(p) for p in ("KUN", "LIF")) or field_name in ("EMPFG", "KNKLI", "PARNR", "KUNAG", "KUNWE", "KUNRE", "KUNRG", "KUNIV", "LIFRE"):
            id_len = min(length, 10)
            return np.array([f"{random.randint(100000, 999999):0{id_len}d}" for _ in range(row_count)])

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

        # 8. Dates: Universal match for ANY SAP date field
        elif "DAT" in field_name or field_name.endswith("DT") or dtype == "DATS":
            return np.full(row_count, "20260315")

        # 9. Times: Universal match for ANY SAP time field
        elif "ZET" in field_name or "TIM" in field_name or "UHR" in field_name or field_name.endswith("TM") or dtype == "TIMS":
            hours = np.random.randint(8, 18, size=row_count)
            mins = np.random.randint(0, 60, size=row_count)
            secs = np.random.randint(0, 60, size=row_count)
            return np.array([f"{h:02d}{m:02d}{s:02d}" for h, m, s in zip(hours, mins, secs)])

        # 10. Statuses & Processing Confirmation Codes
        elif field_name in ("KOSTK", "WBSTK", "FKSTK", "GBSTK", "UVALL", "UVALS", "UVFAK", "UVVLK", "PKSTK", "BSTAT", "BESTQ", "KZVBR"):
            return np.random.choice(["A", "B", "C"], size=row_count, p=[0.5, 0.3, 0.2])

        # 11. Currencies, Units of Measure, Languages
        elif field_name in ("WAERS", "WAERK", "HWAER") or dtype == "CUKY":
            return np.random.choice(["EUR", "USD", "GBP"], size=row_count, p=[0.6, 0.3, 0.1])
        elif field_name in ("MEINS", "VRKME", "GEWEI", "VOLEH") or dtype == "UNIT":
            units = [u[:length] for u in ["PC", "KG", "M", "L", "ST"]]
            return np.random.choice(units, size=row_count, p=[0.4, 0.25, 0.15, 0.1, 0.1])
        elif field_name in ("SPRAS", "LANG") or dtype == "LANG":
            langs = [l[:length] for l in ["E", "D", "F", "ES"]]
            return np.random.choice(langs, size=row_count, p=[0.7, 0.15, 0.1, 0.05])

        # 12. Document & Posting Types
        elif field_name == "AUART":
            return np.random.choice(["OR", "ZOR", "QT", "RE"], size=row_count, p=[0.7, 0.15, 0.1, 0.05])
        elif field_name == "BLART":
            return np.random.choice(["KR", "SA", "KZ", "DR", "DZ"], size=row_count, p=[0.4, 0.3, 0.1, 0.1, 0.1])
        elif field_name == "BSART":
            return np.random.choice(["NB", "UB", "FO"], size=row_count, p=[0.8, 0.15, 0.05])
        elif field_name == "LFART":
            return np.random.choice(["LF", "LR", "NL"], size=row_count)
        elif field_name == "FKART":
            return np.random.choice(["F2", "RE", "S1"], size=row_count)
        elif field_name == "BSCHL":
            return np.random.choice(["01", "11", "40", "50"], size=row_count)
        elif field_name == "KOART":
            return np.random.choice(["S", "D", "K"], size=row_count, p=[0.5, 0.3, 0.2])
        elif field_name == "SHKZG":
            return np.random.choice(["S", "H"], size=row_count, p=[0.6, 0.4])
        elif field_name == "MWSKZ":
            return np.random.choice(["V1", "V2", "A1", "A2", "I0"], size=row_count, p=[0.5, 0.2, 0.15, 0.1, 0.05])
        elif field_name == "ZLSPR":
            return np.random.choice([" ", "A", "B"], size=row_count, p=[0.88, 0.1, 0.02])
        elif field_name == "ZLSCH":
            return np.random.choice(["T", "C", "U", "E"], size=row_count, p=[0.5, 0.3, 0.1, 0.1])
        elif field_name == "ZTERM":
            return np.random.choice(["0001", "0002", "NT30", "PT60"], size=row_count)
        elif field_name in ("USNAM", "ERNAM", "AENAM"):
            return np.random.choice(["SYS_BATCH", "CONSULTANT_A", "FIN_ADMIN", "SAP_USER"], size=row_count)
        elif field_name == "GJAHR":
            return np.random.choice(["2024", "2025", "2026"], size=row_count)

        # 13. Financial Amounts & Quantities
        elif dtype in ("CURR", "DEC", "QUAN") or any(field_name.startswith(p) for p in ("WRB", "DMB", "NET", "MEN", "LFM", "LGM", "KWM", "FKI", "BRG", "NTG", "VOL")):
            amounts = np.random.lognormal(mean=5.5, sigma=1.0, size=row_count)
            return np.round(amounts, 2)
        elif dtype in ("INT1", "INT2", "INT4", "INT8"):
            return np.random.randint(1, 100, size=row_count)
        elif dtype == "FLTP":
            return np.round(np.random.uniform(1.0, 1000.0, size=row_count), 4)

        # 14. Boolean / Single Character Flags
        elif length == 1:
            return np.random.choice([" ", "X"], size=row_count, p=[0.85, 0.15])

        # 15. Names, Addresses, Descriptions
        elif any(kw in field_name for kw in ("NAME", "SORTL")):
            return np.array([f"{self.faker.company()}"[:length] for _ in range(row_count)])
        elif any(kw in field_name for kw in ("CITY", "ORT01", "ORT02")):
            return np.array([self.faker.city()[:length] for _ in range(row_count)])
        elif any(kw in field_name for kw in ("STRAS", "STREET")):
            return np.array([self.faker.street_address()[:length] for _ in range(row_count)])
        elif any(kw in field_name for kw in ("PSTLZ", "POST_CODE")):
            return np.array([f"{random.randint(10000, 99999)}"[:length] for _ in range(row_count)])
        elif field_name in ("LAND1", "COUNTRY"):
            countries = [c[:length] for c in ["DE", "US", "FR", "GB", "NL"]]
            return np.random.choice(countries, size=row_count)
        elif field_name in ("REGIO", "STATE"):
            regions = [r[:length] for r in ["01", "08", "CA", "NY", "TX", "BY"]]
            return np.random.choice(regions, size=row_count)
        elif any(kw in field_name for kw in ("TEXT", "DESC", "BEZEI", "ARKTX", "MAKTX")):
            sample_descs = [
                "Standard Industrial Assembly", "Heavy Duty Roller Bearing",
                "High Precision Coupling", "Electronic Sensor Board",
                "Reinforced Rubber Gasket", "Hex Head Flange Bolt M10",
                "Hydraulic Control Valve", "Modular Steel Frame"
            ]
            return np.random.choice([d[:length] for d in sample_descs], size=row_count)

        # 16. Intelligent Zero-VAL Fallback based on Length & Datatype
        elif dtype == "NUMC":
            max_val = min(10**length - 1, 99999999)
            return np.array([f"{random.randint(1, max_val):0{length}d}" for _ in range(row_count)])
        elif length == 2:
            return np.random.choice(["01", "02", "10", "20", "AA", "BB"], size=row_count)
        elif length == 3:
            return np.random.choice(["A01", "B02", "C10", "100", "200"], size=row_count)
        elif length == 4:
            return np.random.choice(["1000", "2000", "3000", "STD1", "GEN1"], size=row_count)
        else:
            # Clean enterprise code
            return np.random.choice([f"STD_{100 + i}"[:length] for i in range(10)], size=row_count)

    def _generate_single_default_val(self, table_name: str, field_name: str, f_meta: Any) -> Any:
        """Generates a single default value for a child table row."""
        vals = self._generate_default_field(table_name, field_name, f_meta, 1)
        return vals[0]

    def _generate_from_rule(self, rule: FieldRule, row_count: int, f_meta: Any) -> np.ndarray:
        """Executes a custom rule across N rows."""
        rtype = rule.rule_type.lower()
        p = rule.parameters

        if rtype == "choice":
            choices = p.get("choices", ["VAL_A", "VAL_B"])
            weights = p.get("weights")
            return np.random.choice(choices, size=row_count, p=weights)
        elif rtype == "range":
            min_v = p.get("min", 1.0)
            max_v = p.get("max", 1000.0)
            decimals = p.get("decimals", 2)
            vals = np.random.uniform(min_v, max_v, size=row_count)
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
            pool_size = min(250, row_count)
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

            return np.random.choice(pool, size=row_count) if row_count > pool_size else np.array(pool[:row_count])
        else:
            return self._generate_default_field("", rule.field_name, f_meta, row_count)

    def generate_relational_pair(
        self,
        parent_table: str,
        child_table: str,
        parent_count: int = 100,
        custom_rules: Optional[Dict[str, Dict[str, FieldRule]]] = None
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
            parent_df=parent_df
        )
        return {parent_table: parent_df, child_table: child_df}
