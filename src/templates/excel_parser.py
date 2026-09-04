"""
Fault-Tolerant Excel Specification Parser.
Handles column name variations, spaces, capitalization, and syntax quirks gracefully.
"""
import re
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
from ..synthesis.rules import TableGenerationSpec, FieldRule
from ..catalog.sap_catalog import SAPCatalogManager


# Common column aliases for flexible matching
COLUMN_ALIASES = {
    "table_name": ["table_name", "table", "tablename", "table name", "entity", "target_table"],
    "row_count": ["row_count", "rows", "count", "num_rows", "row count", "records"],
    "parent_table": ["parent_table", "parent", "parent table", "header_table", "master_table"],
    "field_name": ["field_name", "field", "fieldname", "column", "column_name", "col", "attribute"],
    "rule_type": ["rule_type", "type", "rule", "generator", "method"],
    "parameters": ["parameters", "params", "values", "rules", "parameters / values", "config", "args"]
}


class FaultTolerantExcelParser:
    """
    Parses user-provided Excel specification workbooks with extreme tolerance for typos and formatting.
    """

    def __init__(self, catalog_manager: Optional[SAPCatalogManager] = None):
        self.catalog = catalog_manager or SAPCatalogManager()

    def parse_workbook(self, file_path_or_bytes: Any) -> Tuple[Dict[str, TableGenerationSpec], Dict[str, Any]]:
        """
        Parses an Excel file and returns:
        (specs_by_table, audit_report)
        Handles arbitrary header rows, misnamed sheets, and single-sheet configurations.
        """
        audit = {
            "sheets_found": [],
            "tables_found": [],
            "rules_applied": 0,
            "warnings": [],
            "valid": True
        }

        try:
            excel_file = pd.ExcelFile(file_path_or_bytes)
        except Exception as e:
            audit["valid"] = False
            audit["warnings"].append(f"Failed to read Excel workbook: {str(e)}")
            return ({}, audit)

        sheet_names = [s.strip() for s in excel_file.sheet_names]
        audit["sheets_found"] = sheet_names

        # 1. Identify Table_Definitions sheet
        table_sheet = self._find_sheet(sheet_names, ["table_definitions", "tables", "table_config", "entities", "sheet1"])
        df_tables = self._read_sheet_with_header_detection(excel_file, table_sheet) if table_sheet else pd.DataFrame()

        # 2. Identify Field_Rules sheet
        rules_sheet = self._find_sheet(sheet_names, ["field_rules", "rules", "fields", "columns", "sheet2"])
        df_rules = self._read_sheet_with_header_detection(excel_file, rules_sheet) if rules_sheet else pd.DataFrame()

        specs: Dict[str, TableGenerationSpec] = {}

        # 3. Parse tables from df_tables if available
        if not df_tables.empty:
            tbl_col = self._match_alias(df_tables.columns, "table_name")
            cnt_col = self._match_alias(df_tables.columns, "row_count")
            parent_col = self._match_alias(df_tables.columns, "parent_table")

            for _, r in df_tables.iterrows():
                if tbl_col and pd.notna(r[tbl_col]):
                    t_name = str(r[tbl_col]).strip().upper()
                    if not t_name or t_name.startswith("#"):
                        continue

                    # Parse row count
                    row_cnt = 100
                    if cnt_col and pd.notna(r[cnt_col]):
                        try:
                            val_str = str(r[cnt_col]).strip()
                            row_cnt = int(float(val_str))
                        except Exception:
                            digits = re.sub(r"[^\d]", "", str(r[cnt_col]).split(".")[0])
                            row_cnt = int(digits) if digits else 100

                    # Parse parent table
                    parent_tbl = None
                    if parent_col and pd.notna(r[parent_col]):
                        p_val = str(r[parent_col]).strip().upper()
                        if p_val and p_val not in ("NAN", "NONE", ""):
                            parent_tbl = p_val

                    specs[t_name] = TableGenerationSpec(
                        table_name=t_name,
                        row_count=max(1, row_cnt),
                        parent_table=parent_tbl
                    )
                    if t_name not in audit["tables_found"]:
                        audit["tables_found"].append(t_name)

            # If df_tables ALSO contains field_name column, parse rules from it too
            fld_in_tables = self._match_alias(df_tables.columns, "field_name")
            if fld_in_tables:
                rule_col = self._match_alias(df_tables.columns, "rule_type")
                param_col = self._match_alias(df_tables.columns, "parameters")
                default_table = table_sheet.strip().upper() if table_sheet else "DATA_TABLE"

                for _, r in df_tables.iterrows():
                    if pd.notna(r[fld_in_tables]):
                        f_name = str(r[fld_in_tables]).strip().upper()
                        if not f_name or f_name.startswith("#"):
                            continue
                        t_name = str(r[tbl_col]).strip().upper() if tbl_col and pd.notna(r[tbl_col]) else default_table
                        r_type = str(r[rule_col]).strip().lower() if rule_col and pd.notna(r[rule_col]) else "choice"
                        params_raw = str(r[param_col]).strip() if param_col and pd.notna(r[param_col]) else ""

                        if t_name not in specs:
                            specs[t_name] = TableGenerationSpec(table_name=t_name, row_count=100)
                            if t_name not in audit["tables_found"]:
                                audit["tables_found"].append(t_name)

                        parsed_rule = self._parse_rule_string(f_name, r_type, params_raw)
                        specs[t_name].rules[f_name] = parsed_rule
                        audit["rules_applied"] += 1

        # 4. If rules sheet identified, parse rules
        if not df_rules.empty:
            tbl_col = self._match_alias(df_rules.columns, "table_name")
            fld_col = self._match_alias(df_rules.columns, "field_name")
            rule_col = self._match_alias(df_rules.columns, "rule_type")
            param_col = self._match_alias(df_rules.columns, "parameters")

            # If no table_name column in rules sheet, use rules_sheet name as table name
            default_table = rules_sheet.strip().upper() if rules_sheet else "DATA_TABLE"

            for _, r in df_rules.iterrows():
                if fld_col and pd.notna(r[fld_col]):
                    f_name = str(r[fld_col]).strip().upper()
                    if not f_name or f_name.startswith("#"):
                        continue

                    t_name = str(r[tbl_col]).strip().upper() if tbl_col and pd.notna(r[tbl_col]) else default_table
                    r_type = str(r[rule_col]).strip().lower() if rule_col and pd.notna(r[rule_col]) else "choice"
                    params_raw = str(r[param_col]).strip() if param_col and pd.notna(r[param_col]) else ""

                    if t_name not in specs:
                        specs[t_name] = TableGenerationSpec(table_name=t_name, row_count=100)
                        if t_name not in audit["tables_found"]:
                            audit["tables_found"].append(t_name)

                    parsed_rule = self._parse_rule_string(f_name, r_type, params_raw)
                    specs[t_name].rules[f_name] = parsed_rule
                    audit["rules_applied"] += 1

        # 5. Deep Scan Fallback: If no specs or no rules applied yet, inspect EVERY sheet in workbook
        if not specs or audit["rules_applied"] == 0:
            for s_name in sheet_names:
                if s_name == table_sheet and not df_tables.empty and fld_in_tables:
                    continue  # Already parsed above
                df_s = self._read_sheet_with_header_detection(excel_file, s_name)
                if df_s.empty:
                    continue

                tbl_col = self._match_alias(df_s.columns, "table_name")
                fld_col = self._match_alias(df_s.columns, "field_name")
                rule_col = self._match_alias(df_s.columns, "rule_type")
                param_col = self._match_alias(df_s.columns, "parameters")

                if fld_col:
                    # Found a rules sheet in an arbitrary sheet!
                    t_name_default = s_name.strip().upper()
                    for _, r in df_s.iterrows():
                        if pd.notna(r[fld_col]):
                            f_name = str(r[fld_col]).strip().upper()
                            t_name = str(r[tbl_col]).strip().upper() if tbl_col and pd.notna(r[tbl_col]) else t_name_default
                            r_type = str(r[rule_col]).strip().lower() if rule_col and pd.notna(r[rule_col]) else "choice"
                            params_raw = str(r[param_col]).strip() if param_col and pd.notna(r[param_col]) else ""

                            if t_name not in specs:
                                specs[t_name] = TableGenerationSpec(table_name=t_name, row_count=100)
                                if t_name not in audit["tables_found"]:
                                    audit["tables_found"].append(t_name)

                            parsed_rule = self._parse_rule_string(f_name, r_type, params_raw)
                            specs[t_name].rules[f_name] = parsed_rule
                            audit["rules_applied"] += 1

        # 6. Sample Data Fallback: If still no specs, treat sheet columns as table fields
        if not specs and sheet_names:
            for s_name in sheet_names:
                df_raw = pd.read_excel(excel_file, sheet_name=s_name)
                cols = [str(c).strip().upper() for c in df_raw.columns if not str(c).startswith("Unnamed:")]
                if cols and len(cols) >= 2:
                    t_name = s_name.strip().upper()
                    if t_name in ("SHEET1", "DATA", "SPEC"):
                        # Infer from first column if it resembles SAP key (e.g. MANDT, VBELN)
                        t_name = "VBAK" if "VBELN" in cols else "BKPF" if "BELNR" in cols else "SAP_TABLE"
                    specs[t_name] = TableGenerationSpec(table_name=t_name, row_count=100)
                    audit["tables_found"].append(t_name)
                    for col_name in cols:
                        specs[t_name].rules[col_name] = self._parse_rule_string(col_name, "choice", "")
                        audit["rules_applied"] += 1
                    break

        if not specs:
            audit["valid"] = False
            audit["warnings"].append(f"Sheets detected: {sheet_names}. Could not locate table or field specification columns.")
            audit["warnings"].append("Expected columns: 'Table_Name', 'Field_Name', 'Rule_Type', 'Parameters'.")
            audit["warnings"].append("Tip: Use the pre-formatted Excel template provided on the studio card.")

        return (specs, audit)

    def _read_sheet_with_header_detection(self, excel_file: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
        """Reads an Excel sheet and automatically locates the header row within the first 6 rows."""
        try:
            df_raw = pd.read_excel(excel_file, sheet_name=sheet_name, header=None)
            if df_raw.empty:
                return pd.DataFrame()

            # Inspect first 6 rows to find where known column keywords appear
            header_row_idx = 0
            found_header = False
            for r_idx in range(min(6, len(df_raw))):
                row_vals = [str(v).strip().lower() for v in df_raw.iloc[r_idx] if pd.notna(v)]
                for concept, aliases in COLUMN_ALIASES.items():
                    if any(alias in val for val in row_vals for alias in aliases):
                        header_row_idx = r_idx
                        found_header = True
                        break
                if found_header:
                    break

            if found_header:
                df = pd.read_excel(excel_file, sheet_name=sheet_name, skiprows=header_row_idx)
            else:
                df = pd.read_excel(excel_file, sheet_name=sheet_name)

            return self._normalize_dataframe_headers(df)
        except Exception:
            return pd.DataFrame()

    def _find_sheet(self, sheets: List[str], candidates: List[str]) -> Optional[str]:
        """Finds matching sheet name case-insensitively, returning None if no candidate matches."""
        for c in candidates:
            for s in sheets:
                if c.lower() in s.lower():
                    return s
        return None

    def _normalize_dataframe_headers(self, df: pd.DataFrame) -> pd.DataFrame:
        """Strips whitespace, replaces multiple spaces, and handles casing."""
        new_cols = []
        for col in df.columns:
            cleaned = re.sub(r"\s+", " ", str(col).strip().lower())
            new_cols.append(cleaned)
        df.columns = new_cols
        return df

    def _match_alias(self, columns: List[str], concept: str) -> Optional[str]:
        """Matches a concept against column aliases."""
        aliases = COLUMN_ALIASES.get(concept, [])
        for col in columns:
            for alias in aliases:
                if alias == col or alias in col:
                    return col
        return None

    def _parse_rule_string(self, field_name: str, rule_type: str, params: str) -> FieldRule:
        """Parses flexible parameter strings with ultra-fault-tolerant syntax handling."""
        parsed_params = {}
        rule_type_clean = rule_type.lower().strip()

        # 1. CHOICE / ENUM / WEIGHTED DISTRIBUTION
        if any(kw in rule_type_clean for kw in ("choice", "enum", "prob", "weight", "distrib")):
            choices = []
            weights = []
            if ":" in params:
                parts = re.split(r"[,;]", params)
                for p in parts:
                    if ":" in p:
                        val, w = p.split(":", 1)
                        val_clean = val.strip().strip("'\"")
                        try:
                            # Support percentage strings (e.g. '70%' -> 70.0)
                            w_clean = w.strip().replace("%", "")
                            weight = float(w_clean)
                        except Exception:
                            weight = 1.0
                        if val_clean:
                            choices.append(val_clean)
                            weights.append(max(0.0, weight))
                # Normalize weights to sum to 1.0
                total_w = sum(weights) or 1.0
                weights = [w / total_w for w in weights]
            else:
                choices = [c.strip().strip("'\"") for c in re.split(r"[,;]", params) if c.strip()]
                weights = None

            parsed_params["choices"] = choices or ["VAL_A", "VAL_B"]
            if weights:
                parsed_params["weights"] = weights
            return FieldRule(field_name=field_name, rule_type="choice", parameters=parsed_params)

        # 2. RANGE / NUMERIC INTERVAL
        elif any(kw in rule_type_clean for kw in ("range", "uniform", "between", "interval", "numeric")):
            min_val = 1.0
            max_val = 1000.0
            decimals = 2

            min_match = re.search(r"min\s*:\s*([\d\.-]+)", params, re.IGNORECASE)
            max_match = re.search(r"max\s*:\s*([\d\.-]+)", params, re.IGNORECASE)
            dec_match = re.search(r"dec\w*\s*:\s*(\d+)", params, re.IGNORECASE)

            if min_match:
                min_val = float(min_match.group(1))
            if max_match:
                max_val = float(max_match.group(1))
            if dec_match:
                decimals = int(dec_match.group(1))

            # Natural range syntax fallback: '10 to 500', '10..500', '10-500'
            if not min_match and not max_match:
                between_match = re.search(r"([\d\.]+)\s*(?:to|\.\.|-)\s*([\d\.]+)", params, re.IGNORECASE)
                if between_match:
                    min_val = float(between_match.group(1))
                    max_val = float(between_match.group(2))

            parsed_params["min"] = min_val
            parsed_params["max"] = max_val
            parsed_params["decimals"] = decimals
            return FieldRule(field_name=field_name, rule_type="range", parameters=parsed_params)

        # 3. FIXED / CONSTANT
        elif any(kw in rule_type_clean for kw in ("fixed", "constant", "static")):
            val = re.sub(r"^(?:value|val|constant|const)\s*:\s*", "", params, flags=re.IGNORECASE).strip().strip("'\"")
            parsed_params["value"] = val
            return FieldRule(field_name=field_name, rule_type="fixed", parameters=parsed_params)

        # 4. FAKER / SEMANTIC PROCEDURAL
        elif any(kw in rule_type_clean for kw in ("faker", "fake", "mock", "semantic")):
            provider = re.sub(r"^(?:provider|type)\s*:\s*", "", params, flags=re.IGNORECASE).strip().lower() or "company"
            parsed_params["provider"] = provider
            return FieldRule(field_name=field_name, rule_type="faker", parameters=parsed_params)

        # 5. SEQUENCE / INCREMENTAL
        elif any(kw in rule_type_clean for kw in ("sequence", "seq", "serial", "counter", "increment", "autoincrement")):
            prefix = ""
            start_val = 10000000
            step_val = 1
            pad_len = 10

            pref_match = re.search(r"prefix\s*:\s*([^,;]+)", params, re.IGNORECASE)
            if pref_match:
                prefix = pref_match.group(1).strip().strip("'\"")

            start_match = re.search(r"start\s*:\s*(\d+)", params, re.IGNORECASE)
            if start_match:
                start_val = int(start_match.group(1))

            step_match = re.search(r"step\s*:\s*(\d+)", params, re.IGNORECASE)
            if step_match:
                step_val = int(step_match.group(1))

            pad_match = re.search(r"(?:pad|length|len)\s*:\s*(\d+)", params, re.IGNORECASE)
            if pad_match:
                pad_len = int(pad_match.group(1))

            # Fallback simple start/end syntax: '1..1000'
            if not start_match:
                simple_seq = re.search(r"^(\d+)\s*(?:\.\.|to|-)\s*(\d+)", params)
                if simple_seq:
                    start_val = int(simple_seq.group(1))

            parsed_params["prefix"] = prefix
            parsed_params["start"] = start_val
            parsed_params["step"] = step_val
            parsed_params["pad"] = pad_len
            return FieldRule(field_name=field_name, rule_type="sequence", parameters=parsed_params)

        else:
            # Fallback choice
            clean_choice = params.strip().strip("'\"")
            return FieldRule(field_name=field_name, rule_type="choice", parameters={"choices": [clean_choice] if clean_choice else ["VAL_1"]})
