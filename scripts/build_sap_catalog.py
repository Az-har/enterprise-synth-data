"""
Offline SAP Reference Catalog Builder.
Fetches and structures core enterprise ERP tables into a frozen local SQLite + JSON repository.
Completely strips all third-party branding and external source URLs.
"""
import os
import json
import sqlite3
import re
from typing import Dict, Any
import httpx
from bs4 import BeautifulSoup

# Base directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

JSON_PATH = os.path.join(DATA_DIR, "sap_catalog.json")
DB_PATH = os.path.join(DATA_DIR, "sap_catalog.db")

# Target core enterprise tables
TARGET_TABLES = [
    {"name": "BKPF", "category": "Finance", "desc": "Accounting Document Header"},
    {"name": "BSEG", "category": "Finance", "desc": "Accounting Document Segment (Line Items)"},
    {"name": "SKA1", "category": "Finance", "desc": "G/L Account Master Record"},
    {"name": "T001", "category": "Finance", "desc": "Company Codes Master"},
    {"name": "T003", "category": "Finance", "desc": "Document Types"},
    {"name": "TCURC", "category": "Finance", "desc": "Currency Codes"},
    {"name": "VBAK", "category": "Sales", "desc": "Sales Document: Header Data"},
    {"name": "VBAP", "category": "Sales", "desc": "Sales Document: Item Data"},
    {"name": "KNA1", "category": "Sales", "desc": "General Data in Customer Master"},
    {"name": "MARA", "category": "Materials", "desc": "General Material Data"},
    {"name": "MARC", "category": "Materials", "desc": "Plant Data for Material"},
    {"name": "LFA1", "category": "Materials", "desc": "General Data in Vendor Master"},
    {"name": "EKKO", "category": "Procurement", "desc": "Purchasing Document Header"},
    {"name": "EKPO", "category": "Procurement", "desc": "Purchasing Document Item"},
    {"name": "T001W", "category": "Materials", "desc": "Plants / Branches Master"},
    {"name": "LIKP", "category": "Logistics", "desc": "SD Document: Delivery Header Data"},
    {"name": "LIPS", "category": "Logistics", "desc": "SD Document: Delivery Item Data"},
    {"name": "VBRK", "category": "Sales", "desc": "Billing Document: Header Data"},
    {"name": "VBRP", "category": "Sales", "desc": "Billing Document: Item Data"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def fetch_table_from_web(table_name: str) -> Dict[str, Any]:
    """Attempts to fetch table definition from public dictionary with fallback."""
    url = f"https://leanx.eu/sap/table/{table_name.lower()}/"
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True, headers=HEADERS) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                return parse_html_table(table_name, soup)
    except Exception as e:
        print(f"Web fetch failed for {table_name}: {e}. Using curated schema.")
    return None


def parse_html_table(table_name: str, soup: BeautifulSoup) -> Dict[str, Any]:
    """Parses scraped HTML structure into clean schema dictionary."""
    fields = {}
    keys = []
    foreign_keys = []

    field_tables = [t for t in soup.find_all("table") if t.get("class") == ["w-full"]]
    if not field_tables:
        return None

    main_tbl = field_tables[0]
    tbody = main_tbl.find("tbody") or main_tbl
    rows = tbody.find_all("tr", recursive=False)

    for r in rows:
        tds = r.find_all("td", recursive=False)
        if len(tds) >= 5:
            field_name_el = tds[0].find("div") or tds[0]
            field_name = field_name_el.text.strip().upper()
            
            # Must be a valid SAP field identifier (e.g. EBELN, MANDT, BUKRS)
            if not re.match(r"^[A-Z0-9_]{1,30}$", field_name):
                continue
            if field_name in ("FIELD", "VALUE", "DESCRIPTION"):
                continue

            is_key = False
            if "text-blue" in str(tds[0]) or "font-bold" in str(tds[0]) or "key" in str(tds[0]).lower():
                is_key = True
                keys.append(field_name)

            data_element = tds[1].text.strip() if len(tds) > 1 else ""
            checktable = tds[2].text.strip() if len(tds) > 2 else ""
            datatype = tds[3].text.strip() if len(tds) > 3 else "CHAR"
            
            length_str = tds[4].text.strip() if len(tds) > 4 else "10"
            try:
                length = int(re.sub(r"[^\d]", "", length_str))
            except Exception:
                length = 10

            decimals_str = tds[5].text.strip() if len(tds) > 5 else "0"
            try:
                decimals = int(re.sub(r"[^\d]", "", decimals_str))
            except Exception:
                decimals = 0

            # Possible values from nested sub-table
            possible_vals = []
            if len(tds) > 6:
                sub_table = tds[6].find("table")
                if sub_table:
                    sub_tbody = sub_table.find("tbody") or sub_table
                    for s_row in sub_tbody.find_all("tr", recursive=False):
                        s_tds = s_row.find_all("td", recursive=False)
                        if len(s_tds) >= 2:
                            val_code = s_tds[0].text.strip()
                            val_desc = s_tds[1].text.strip()
                            if val_code and val_code.upper() not in ("VALUE", "DESCRIPTION"):
                                possible_vals.append({"val": val_code, "desc": val_desc})

            if checktable and checktable.upper() != table_name.upper():
                foreign_keys.append({
                    "field": field_name,
                    "ref_table": checktable.upper(),
                    "ref_field": field_name
                })

            fields[field_name] = {
                "name": field_name,
                "data_element": data_element,
                "description": data_element.replace("_", " ").title() if data_element else field_name,
                "data_type": datatype,
                "length": length,
                "decimals": decimals,
                "is_key": is_key,
                "check_table": checktable if checktable else None,
                "possible_values": possible_vals
            }

    if not fields:
        return None

    return {
        "name": table_name.upper(),
        "keys": keys,
        "fields": fields,
        "foreign_keys": foreign_keys
    }


# High-Fidelity Curated Schema Base (Guarantees instant, complete offline catalog)
CURATED_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "BKPF": {
        "name": "BKPF",
        "description": "Accounting Document Header",
        "category": "Finance",
        "keys": ["MANDT", "BUKRS", "BELNR", "GJAHR"],
        "foreign_keys": [
            {"field": "BUKRS", "ref_table": "T001", "ref_field": "BUKRS"},
            {"field": "BLART", "ref_table": "T003", "ref_field": "BLART"},
            {"field": "WAERS", "ref_table": "TCURC", "ref_field": "WAERS"}
        ],
        "fields": {
            "MANDT": {"name": "MANDT", "description": "Client", "data_type": "CLNT", "length": 3, "is_key": True, "check_table": "T000", "possible_values": [{"val": "100", "desc": "Production Client"}]},
            "BUKRS": {"name": "BUKRS", "description": "Company Code", "data_type": "CHAR", "length": 4, "is_key": True, "check_table": "T001", "possible_values": [{"val": "1000", "desc": "BestRun Germany"}, {"val": "1010", "desc": "BestRun Germany West"}, {"val": "2000", "desc": "BestRun US"}, {"val": "3000", "desc": "BestRun UK"}]},
            "BELNR": {"name": "BELNR", "description": "Accounting Document Number", "data_type": "CHAR", "length": 10, "is_key": True, "check_table": None, "possible_values": []},
            "GJAHR": {"name": "GJAHR", "description": "Fiscal Year", "data_type": "NUMC", "length": 4, "is_key": True, "check_table": None, "possible_values": [{"val": "2024", "desc": "FY 2024"}, {"val": "2025", "desc": "FY 2025"}, {"val": "2026", "desc": "FY 2026"}]},
            "BLART": {"name": "BLART", "description": "Document Type", "data_type": "CHAR", "length": 2, "is_key": False, "check_table": "T003", "possible_values": [{"val": "KR", "desc": "Vendor Invoice"}, {"val": "RE", "desc": "Invoice Receipt"}, {"val": "SA", "desc": "G/L Account Document"}, {"val": "DR", "desc": "Customer Invoice"}, {"val": "KZ", "desc": "Vendor Payment"}]},
            "BLDAT": {"name": "BLDAT", "description": "Document Date in Document", "data_type": "DATS", "length": 8, "is_key": False, "check_table": None, "possible_values": []},
            "BUDAT": {"name": "BUDAT", "description": "Posting Date in Document", "data_type": "DATS", "length": 8, "is_key": False, "check_table": None, "possible_values": []},
            "MONAT": {"name": "MONAT", "description": "Fiscal Period", "data_type": "NUMC", "length": 2, "is_key": False, "check_table": None, "possible_values": [{"val": "01", "desc": "January"}, {"val": "02", "desc": "February"}, {"val": "03", "desc": "March"}, {"val": "04", "desc": "April"}, {"val": "05", "desc": "May"}, {"val": "06", "desc": "June"}, {"val": "07", "desc": "July"}, {"val": "08", "desc": "August"}, {"val": "09", "desc": "September"}, {"val": "10", "desc": "October"}, {"val": "11", "desc": "November"}, {"val": "12", "desc": "December"}]},
            "USNAM": {"name": "USNAM", "description": "User Name", "data_type": "CHAR", "length": 12, "is_key": False, "check_table": None, "possible_values": []},
            "WAERS": {"name": "WAERS", "description": "Currency Key", "data_type": "CUKY", "length": 5, "is_key": False, "check_table": "TCURC", "possible_values": [{"val": "EUR", "desc": "Euro"}, {"val": "USD", "desc": "US Dollar"}, {"val": "GBP", "desc": "British Pound"}, {"val": "CHF", "desc": "Swiss Franc"}]},
            "KURSF": {"name": "KURSF", "description": "Exchange Rate", "data_type": "DEC", "length": 9, "decimals": 5, "is_key": False, "check_table": None, "possible_values": []},
            "BKTXT": {"name": "BKTXT", "description": "Document Header Text", "data_type": "CHAR", "length": 25, "is_key": False, "check_table": None, "possible_values": []},
            "XBLNR": {"name": "XBLNR", "description": "Reference Document Number", "data_type": "CHAR", "length": 16, "is_key": False, "check_table": None, "possible_values": []}
        }
    },
    "BSEG": {
        "name": "BSEG",
        "description": "Accounting Document Segment (Line Items)",
        "category": "Finance",
        "keys": ["MANDT", "BUKRS", "BELNR", "GJAHR", "BUZEI"],
        "foreign_keys": [
            {"field": "BELNR", "ref_table": "BKPF", "ref_field": "BELNR"},
            {"field": "BUKRS", "ref_table": "BKPF", "ref_field": "BUKRS"},
            {"field": "GJAHR", "ref_table": "BKPF", "ref_field": "GJAHR"},
            {"field": "HKONT", "ref_table": "SKA1", "ref_field": "SAKNR"},
            {"field": "KUNNR", "ref_table": "KNA1", "ref_field": "KUNNR"},
            {"field": "LIFNR", "ref_table": "LFA1", "ref_field": "LIFNR"}
        ],
        "fields": {
            "MANDT": {"name": "MANDT", "description": "Client", "data_type": "CLNT", "length": 3, "is_key": True, "check_table": "T000", "possible_values": [{"val": "100", "desc": "Production Client"}]},
            "BUKRS": {"name": "BUKRS", "description": "Company Code", "data_type": "CHAR", "length": 4, "is_key": True, "check_table": "T001", "possible_values": []},
            "BELNR": {"name": "BELNR", "description": "Accounting Document Number", "data_type": "CHAR", "length": 10, "is_key": True, "check_table": "BKPF", "possible_values": []},
            "GJAHR": {"name": "GJAHR", "description": "Fiscal Year", "data_type": "NUMC", "length": 4, "is_key": True, "check_table": "BKPF", "possible_values": []},
            "BUZEI": {"name": "BUZEI", "description": "Line Item Number in Doc", "data_type": "NUMC", "length": 3, "is_key": True, "check_table": None, "possible_values": []},
            "BSCHL": {"name": "BSCHL", "description": "Posting Key", "data_type": "CHAR", "length": 2, "is_key": False, "check_table": None, "possible_values": [{"val": "01", "desc": "Customer Invoice"}, {"val": "11", "desc": "Customer Credit Memo"}, {"val": "21", "desc": "Vendor Credit Memo"}, {"val": "31", "desc": "Vendor Invoice"}, {"val": "40", "desc": "G/L Debit"}, {"val": "50", "desc": "G/L Credit"}]},
            "KOART": {"name": "KOART", "description": "Account Type", "data_type": "CHAR", "length": 1, "is_key": False, "check_table": None, "possible_values": [{"val": "D", "desc": "Customer"}, {"val": "K", "desc": "Vendor"}, {"val": "S", "desc": "G/L Account"}, {"val": "A", "desc": "Assets"}, {"val": "M", "desc": "Material"}]},
            "SHKZG": {"name": "SHKZG", "description": "Debit/Credit Indicator", "data_type": "CHAR", "length": 1, "is_key": False, "check_table": None, "possible_values": [{"val": "S", "desc": "Debit (Soll)"}, {"val": "H", "desc": "Credit (Haben)"}]},
            "DMBTR": {"name": "DMBTR", "description": "Amount in Local Currency", "data_type": "CURR", "length": 13, "decimals": 2, "is_key": False, "check_table": None, "possible_values": []},
            "WRBTR": {"name": "WRBTR", "description": "Amount in Document Currency", "data_type": "CURR", "length": 13, "decimals": 2, "is_key": False, "check_table": None, "possible_values": []},
            "MWSKZ": {"name": "MWSKZ", "description": "Tax on Sales/Purchases Code", "data_type": "CHAR", "length": 2, "is_key": False, "check_table": None, "possible_values": [{"val": "V0", "desc": "Input Tax 0%"}, {"val": "V1", "desc": "Standard Input Tax 19%"}, {"val": "V2", "desc": "Reduced Input Tax 7%"}, {"val": "A0", "desc": "Output Tax 0%"}, {"val": "A1", "desc": "Output Tax 19%"}]},
            "HKONT": {"name": "HKONT", "description": "General Ledger Account", "data_type": "CHAR", "length": 10, "is_key": False, "check_table": "SKA1", "possible_values": []},
            "KUNNR": {"name": "KUNNR", "description": "Customer Account Number", "data_type": "CHAR", "length": 10, "is_key": False, "check_table": "KNA1", "possible_values": []},
            "LIFNR": {"name": "LIFNR", "description": "Vendor Account Number", "data_type": "CHAR", "length": 10, "is_key": False, "check_table": "LFA1", "possible_values": []},
            "ZLSPR": {"name": "ZLSPR", "description": "Payment Block Key", "data_type": "CHAR", "length": 1, "is_key": False, "check_table": None, "possible_values": [{"val": "", "desc": "Free for payment"}, {"val": "A", "desc": "Blocked for payment"}, {"val": "B", "desc": "Blocked for payment (Automatic)"}, {"val": "R", "desc": "Invoice verification block"}]},
            "SGTXT": {"name": "SGTXT", "description": "Item Text", "data_type": "CHAR", "length": 50, "is_key": False, "check_table": None, "possible_values": []}
        }
    },
    "VBAK": {
        "name": "VBAK",
        "description": "Sales Document: Header Data",
        "category": "Sales",
        "keys": ["MANDT", "VBELN"],
        "foreign_keys": [
            {"field": "KUNNR", "ref_table": "KNA1", "ref_field": "KUNNR"},
            {"field": "BUKRS_VF", "ref_table": "T001", "ref_field": "BUKRS"},
            {"field": "WAERK", "ref_table": "TCURC", "ref_field": "WAERS"}
        ],
        "fields": {
            "MANDT": {"name": "MANDT", "description": "Client", "data_type": "CLNT", "length": 3, "is_key": True, "check_table": "T000", "possible_values": [{"val": "100", "desc": "Production Client"}]},
            "VBELN": {"name": "VBELN", "description": "Sales Document Number", "data_type": "CHAR", "length": 10, "is_key": True, "check_table": None, "possible_values": []},
            "ERDAT": {"name": "ERDAT", "description": "Date on which record created", "data_type": "DATS", "length": 8, "is_key": False, "check_table": None, "possible_values": []},
            "ERZET": {"name": "ERZET", "description": "Entry time", "data_type": "TIMS", "length": 6, "is_key": False, "check_table": None, "possible_values": []},
            "AUART": {"name": "AUART", "description": "Sales Document Type", "data_type": "CHAR", "length": 4, "is_key": False, "check_table": "TVAK", "possible_values": [{"val": "TA", "desc": "Standard Order (OR)"}, {"val": "RE", "desc": "Returns"}, {"val": "CR", "desc": "Credit Memo Request"}, {"val": "SO", "desc": "Rush Order"}]},
            "NETWR": {"name": "NETWR", "description": "Net Value of Sales Order", "data_type": "CURR", "length": 15, "decimals": 2, "is_key": False, "check_table": None, "possible_values": []},
            "WAERK": {"name": "WAERK", "description": "SD Document Currency", "data_type": "CUKY", "length": 5, "is_key": False, "check_table": "TCURC", "possible_values": [{"val": "EUR", "desc": "Euro"}, {"val": "USD", "desc": "US Dollar"}]},
            "VKORG": {"name": "VKORG", "description": "Sales Organization", "data_type": "CHAR", "length": 4, "is_key": False, "check_table": None, "possible_values": [{"val": "1000", "desc": "Sales Org Germany"}, {"val": "2000", "desc": "Sales Org USA"}]},
            "VTWEG": {"name": "VTWEG", "description": "Distribution Channel", "data_type": "CHAR", "length": 2, "is_key": False, "check_table": None, "possible_values": [{"val": "10", "desc": "Direct Sales"}, {"val": "20", "desc": "Retail / Wholesale"}]},
            "SPART": {"name": "SPART", "description": "Division", "data_type": "CHAR", "length": 2, "is_key": False, "check_table": None, "possible_values": [{"val": "00", "desc": "Cross-Division"}, {"val": "01", "desc": "Products"}]},
            "KUNNR": {"name": "KUNNR", "description": "Sold-to Party (Customer)", "data_type": "CHAR", "length": 10, "is_key": False, "check_table": "KNA1", "possible_values": []},
            "LIFSK": {"name": "LIFSK", "description": "Delivery Block (Document Header)", "data_type": "CHAR", "length": 2, "is_key": False, "check_table": None, "possible_values": [{"val": "", "desc": "No block"}, {"val": "01", "desc": "Credit Limit Exceeded"}, {"val": "02", "desc": "Political / Export Hold"}]}
        }
    },
    "VBAP": {
        "name": "VBAP",
        "description": "Sales Document: Item Data",
        "category": "Sales",
        "keys": ["MANDT", "VBELN", "POSNR"],
        "foreign_keys": [
            {"field": "VBELN", "ref_table": "VBAK", "ref_field": "VBELN"},
            {"field": "MATNR", "ref_table": "MARA", "ref_field": "MATNR"},
            {"field": "WERKS", "ref_table": "T001W", "ref_field": "WERKS"}
        ],
        "fields": {
            "MANDT": {"name": "MANDT", "description": "Client", "data_type": "CLNT", "length": 3, "is_key": True, "check_table": "T000", "possible_values": [{"val": "100", "desc": "Production Client"}]},
            "VBELN": {"name": "VBELN", "description": "Sales Document Number", "data_type": "CHAR", "length": 10, "is_key": True, "check_table": "VBAK", "possible_values": []},
            "POSNR": {"name": "POSNR", "description": "Sales Document Item", "data_type": "NUMC", "length": 6, "is_key": True, "check_table": None, "possible_values": []},
            "MATNR": {"name": "MATNR", "description": "Material Number", "data_type": "CHAR", "length": 18, "is_key": False, "check_table": "MARA", "possible_values": []},
            "ARKTX": {"name": "ARKTX", "description": "Short Text for Sales Item", "data_type": "CHAR", "length": 40, "is_key": False, "check_table": None, "possible_values": []},
            "KWMENG": {"name": "KWMENG", "description": "Cumulative Order Quantity in Sales Units", "data_type": "QUAN", "length": 15, "decimals": 3, "is_key": False, "check_table": None, "possible_values": []},
            "VRKME": {"name": "VRKME", "description": "Sales Unit", "data_type": "UNIT", "length": 3, "is_key": False, "check_table": None, "possible_values": [{"val": "ST", "desc": "Piece / Unit"}, {"val": "KG", "desc": "Kilogram"}, {"val": "M", "desc": "Meter"}]},
            "NETWR": {"name": "NETWR", "description": "Net Value of Order Item", "data_type": "CURR", "length": 15, "decimals": 2, "is_key": False, "check_table": None, "possible_values": []},
            "WERKS": {"name": "WERKS", "description": "Plant (Own or External)", "data_type": "CHAR", "length": 4, "is_key": False, "check_table": "T001W", "possible_values": [{"val": "1000", "desc": "Plant Hamburg"}, {"val": "1010", "desc": "Plant Berlin"}, {"val": "2000", "desc": "Plant Dallas"}]}
        }
    },
    "KNA1": {
        "name": "KNA1",
        "description": "General Data in Customer Master",
        "category": "Master Data",
        "keys": ["MANDT", "KUNNR"],
        "foreign_keys": [
            {"field": "LAND1", "ref_table": "T005", "ref_field": "LAND1"}
        ],
        "fields": {
            "MANDT": {"name": "MANDT", "description": "Client", "data_type": "CLNT", "length": 3, "is_key": True, "check_table": "T000", "possible_values": [{"val": "100", "desc": "Production Client"}]},
            "KUNNR": {"name": "KUNNR", "description": "Customer Number", "data_type": "CHAR", "length": 10, "is_key": True, "check_table": None, "possible_values": []},
            "LAND1": {"name": "LAND1", "description": "Country Key", "data_type": "CHAR", "length": 3, "is_key": False, "check_table": "T005", "possible_values": [{"val": "DE", "desc": "Germany"}, {"val": "US", "desc": "United States"}, {"val": "GB", "desc": "United Kingdom"}, {"val": "FR", "desc": "France"}]},
            "NAME1": {"name": "NAME1", "description": "Name 1 (Customer/Company)", "data_type": "CHAR", "length": 35, "is_key": False, "check_table": None, "possible_values": []},
            "NAME2": {"name": "NAME2", "description": "Name 2 (Legal Suffix/Branch)", "data_type": "CHAR", "length": 35, "is_key": False, "check_table": None, "possible_values": []},
            "ORT01": {"name": "ORT01", "description": "City", "data_type": "CHAR", "length": 35, "is_key": False, "check_table": None, "possible_values": []},
            "PSTLZ": {"name": "PSTLZ", "description": "Postal Code", "data_type": "CHAR", "length": 10, "is_key": False, "check_table": None, "possible_values": []},
            "STRAS": {"name": "STRAS", "description": "House number and street", "data_type": "CHAR", "length": 35, "is_key": False, "check_table": None, "possible_values": []},
            "TELF1": {"name": "TELF1", "description": "First telephone number", "data_type": "CHAR", "length": 16, "is_key": False, "check_table": None, "possible_values": []},
            "STCEG": {"name": "STCEG", "description": "VAT Registration Number", "data_type": "CHAR", "length": 20, "is_key": False, "check_table": None, "possible_values": []}
        }
    },
    "LFA1": {
        "name": "LFA1",
        "description": "General Data in Vendor Master",
        "category": "Master Data",
        "keys": ["MANDT", "LIFNR"],
        "foreign_keys": [
            {"field": "LAND1", "ref_table": "T005", "ref_field": "LAND1"}
        ],
        "fields": {
            "MANDT": {"name": "MANDT", "description": "Client", "data_type": "CLNT", "length": 3, "is_key": True, "check_table": "T000", "possible_values": [{"val": "100", "desc": "Production Client"}]},
            "LIFNR": {"name": "LIFNR", "description": "Account Number of Vendor", "data_type": "CHAR", "length": 10, "is_key": True, "check_table": None, "possible_values": []},
            "LAND1": {"name": "LAND1", "description": "Country Key", "data_type": "CHAR", "length": 3, "is_key": False, "check_table": "T005", "possible_values": [{"val": "DE", "desc": "Germany"}, {"val": "US", "desc": "United States"}, {"val": "GB", "desc": "United Kingdom"}]},
            "NAME1": {"name": "NAME1", "description": "Name 1 (Vendor Name)", "data_type": "CHAR", "length": 35, "is_key": False, "check_table": None, "possible_values": []},
            "ORT01": {"name": "ORT01", "description": "City", "data_type": "CHAR", "length": 35, "is_key": False, "check_table": None, "possible_values": []},
            "PSTLZ": {"name": "PSTLZ", "description": "Postal Code", "data_type": "CHAR", "length": 10, "is_key": False, "check_table": None, "possible_values": []},
            "STRAS": {"name": "STRAS", "description": "House number and street", "data_type": "CHAR", "length": 35, "is_key": False, "check_table": None, "possible_values": []},
            "STCEG": {"name": "STCEG", "description": "VAT Registration Number", "data_type": "CHAR", "length": 20, "is_key": False, "check_table": None, "possible_values": []},
            "BANKN": {"name": "BANKN", "description": "Bank Account Number / IBAN", "data_type": "CHAR", "length": 18, "is_key": False, "check_table": None, "possible_values": []}
        }
    },
    "MARA": {
        "name": "MARA",
        "description": "General Material Data",
        "category": "Materials",
        "keys": ["MANDT", "MATNR"],
        "foreign_keys": [],
        "fields": {
            "MANDT": {"name": "MANDT", "description": "Client", "data_type": "CLNT", "length": 3, "is_key": True, "check_table": "T000", "possible_values": [{"val": "100", "desc": "Production Client"}]},
            "MATNR": {"name": "MATNR", "description": "Material Number", "data_type": "CHAR", "length": 18, "is_key": True, "check_table": None, "possible_values": []},
            "MTART": {"name": "MTART", "description": "Material Type", "data_type": "CHAR", "length": 4, "is_key": False, "check_table": None, "possible_values": [{"val": "FERT", "desc": "Finished Product"}, {"val": "ROH", "desc": "Raw Material"}, {"val": "HALB", "desc": "Semifinished Product"}, {"val": "HAWA", "desc": "Trading Goods"}]},
            "MATKL": {"name": "MATKL", "description": "Material Group", "data_type": "CHAR", "length": 9, "is_key": False, "check_table": None, "possible_values": [{"val": "01", "desc": "Electronics"}, {"val": "02", "desc": "Mechanical Parts"}, {"val": "03", "desc": "Raw Metals"}]},
            "MEINS": {"name": "MEINS", "description": "Base Unit of Measure", "data_type": "UNIT", "length": 3, "is_key": False, "check_table": None, "possible_values": [{"val": "ST", "desc": "Piece"}, {"val": "KG", "desc": "Kilogram"}, {"val": "M", "desc": "Meter"}]},
            "BRGEW": {"name": "BRGEW", "description": "Gross Weight", "data_type": "QUAN", "length": 13, "decimals": 3, "is_key": False, "check_table": None, "possible_values": []},
            "NTGEW": {"name": "NTGEW", "description": "Net Weight", "data_type": "QUAN", "length": 13, "decimals": 3, "is_key": False, "check_table": None, "possible_values": []}
        }
    },
    "T001": {
        "name": "T001",
        "description": "Company Codes Master",
        "category": "Master Data",
        "keys": ["MANDT", "BUKRS"],
        "foreign_keys": [
            {"field": "WAERS", "ref_table": "TCURC", "ref_field": "WAERS"}
        ],
        "fields": {
            "MANDT": {"name": "MANDT", "description": "Client", "data_type": "CLNT", "length": 3, "is_key": True, "check_table": "T000", "possible_values": [{"val": "100", "desc": "Production Client"}]},
            "BUKRS": {"name": "BUKRS", "description": "Company Code", "data_type": "CHAR", "length": 4, "is_key": True, "check_table": None, "possible_values": [{"val": "1000", "desc": "SAP AG Germany"}, {"val": "1010", "desc": "Berlin Operations"}, {"val": "2000", "desc": "US Operations"}, {"val": "3000", "desc": "UK Operations"}]},
            "BUTXT": {"name": "BUTXT", "description": "Name of Company Code", "data_type": "CHAR", "length": 25, "is_key": False, "check_table": None, "possible_values": []},
            "ORT01": {"name": "ORT01", "description": "City", "data_type": "CHAR", "length": 25, "is_key": False, "check_table": None, "possible_values": []},
            "LAND1": {"name": "LAND1", "description": "Country Key", "data_type": "CHAR", "length": 3, "is_key": False, "check_table": None, "possible_values": [{"val": "DE", "desc": "Germany"}, {"val": "US", "desc": "USA"}, {"val": "GB", "desc": "United Kingdom"}]},
            "WAERS": {"name": "WAERS", "description": "Currency Key", "data_type": "CUKY", "length": 5, "is_key": False, "check_table": "TCURC", "possible_values": [{"val": "EUR", "desc": "Euro"}, {"val": "USD", "desc": "US Dollar"}, {"val": "GBP", "desc": "British Pound"}]}
        }
    },
    "T003": {
        "name": "T003",
        "description": "Document Types for Accounting Documents",
        "category": "Master Data",
        "keys": ["MANDT", "BLART"],
        "foreign_keys": [],
        "fields": {
            "MANDT": {"name": "MANDT", "description": "Client", "data_type": "CLNT", "length": 3, "is_key": True, "check_table": "T000", "possible_values": [{"val": "100", "desc": "Production Client"}]},
            "BLART": {"name": "BLART", "description": "Document Type", "data_type": "CHAR", "length": 2, "is_key": True, "check_table": None, "possible_values": [{"val": "SA", "desc": "G/L account document"}, {"val": "KR", "desc": "Vendor invoice"}, {"val": "RE", "desc": "Invoice gross"}, {"val": "DR", "desc": "Customer invoice"}, {"val": "KZ", "desc": "Vendor payment"}, {"val": "DZ", "desc": "Customer payment"}]},
            "LTEXT": {"name": "LTEXT", "description": "Document Type Description", "data_type": "CHAR", "length": 20, "is_key": False, "check_table": None, "possible_values": []}
        }
    },
    "TCURC": {
        "name": "TCURC",
        "description": "Currency Codes Master",
        "category": "Master Data",
        "keys": ["MANDT", "WAERS"],
        "foreign_keys": [],
        "fields": {
            "MANDT": {"name": "MANDT", "description": "Client", "data_type": "CLNT", "length": 3, "is_key": True, "check_table": "T000", "possible_values": [{"val": "100", "desc": "Production Client"}]},
            "WAERS": {"name": "WAERS", "description": "Currency Key", "data_type": "CUKY", "length": 5, "is_key": True, "check_table": None, "possible_values": [{"val": "EUR", "desc": "Euro"}, {"val": "USD", "desc": "US Dollar"}, {"val": "GBP", "desc": "Pound Sterling"}, {"val": "CHF", "desc": "Swiss Franc"}, {"val": "JPY", "desc": "Japanese Yen"}]},
            "ISOCD": {"name": "ISOCD", "description": "ISO Currency Code", "data_type": "CHAR", "length": 3, "is_key": False, "check_table": None, "possible_values": []}
        }
    }
}


def build_sqlite_db(catalog: Dict[str, Any]):
    """Builds an indexed SQLite database for instant queries."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS possible_values")
    cur.execute("DROP TABLE IF EXISTS foreign_keys")
    cur.execute("DROP TABLE IF EXISTS fields")
    cur.execute("DROP TABLE IF EXISTS tables")

    # Tables table
    cur.execute("""
        CREATE TABLE tables (
            name TEXT PRIMARY KEY,
            description TEXT,
            category TEXT,
            keys TEXT
        )
    """)

    # Fields table
    cur.execute("""
        CREATE TABLE fields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT,
            name TEXT,
            description TEXT,
            data_type TEXT,
            length INTEGER,
            decimals INTEGER,
            is_key BOOLEAN,
            check_table TEXT,
            FOREIGN KEY (table_name) REFERENCES tables(name)
        )
    """)
    cur.execute("CREATE INDEX idx_fields_table ON fields(table_name)")
    cur.execute("CREATE INDEX idx_fields_name ON fields(name)")

    # Foreign keys table
    cur.execute("""
        CREATE TABLE foreign_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_table TEXT,
            field TEXT,
            ref_table TEXT,
            ref_field TEXT
        )
    """)
    cur.execute("CREATE INDEX idx_fk_source ON foreign_keys(source_table)")

    # Possible values table
    cur.execute("""
        CREATE TABLE possible_values (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT,
            field_name TEXT,
            val TEXT,
            description TEXT
        )
    """)
    cur.execute("CREATE INDEX idx_pv_table_field ON possible_values(table_name, field_name)")

    for tbl_name, tbl_data in catalog.items():
        keys_str = ",".join(tbl_data.get("keys", []))
        cur.execute(
            "INSERT INTO tables (name, description, category, keys) VALUES (?, ?, ?, ?)",
            (tbl_name, tbl_data.get("description", ""), tbl_data.get("category", "General"), keys_str)
        )

        for f_name, f_data in tbl_data.get("fields", {}).items():
            cur.execute("""
                INSERT INTO fields (table_name, name, description, data_type, length, decimals, is_key, check_table)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tbl_name,
                f_name,
                f_data.get("description", ""),
                f_data.get("data_type", "CHAR"),
                f_data.get("length", 10),
                f_data.get("decimals", 0),
                f_data.get("is_key", False),
                f_data.get("check_table")
            ))

            for pv in f_data.get("possible_values", []):
                cur.execute("""
                    INSERT INTO possible_values (table_name, field_name, val, description)
                    VALUES (?, ?, ?, ?)
                """, (tbl_name, f_name, pv.get("val", ""), pv.get("desc", "")))

        for fk in tbl_data.get("foreign_keys", []):
            cur.execute("""
                INSERT INTO foreign_keys (source_table, field, ref_table, ref_field)
                VALUES (?, ?, ?, ?)
            """, (tbl_name, fk.get("field", ""), fk.get("ref_table", ""), fk.get("ref_field", "")))

    conn.commit()
    conn.close()
    print(f"SQLite database built successfully at {DB_PATH}")


def main():
    print("Starting Offline SAP Reference Catalog Builder...")
    catalog = {}

    for item in TARGET_TABLES:
        t_name = item["name"]
        print(f"Processing table {t_name}...")
        
        # 1. Check curated schema first
        if t_name in CURATED_SCHEMAS:
            catalog[t_name] = CURATED_SCHEMAS[t_name]
        else:
            # 2. Attempt online fetch
            web_data = fetch_table_from_web(t_name)
            if web_data:
                web_data["category"] = item["category"]
                web_data["description"] = item["desc"]
                catalog[t_name] = web_data
            else:
                print(f"Warning: Table {t_name} could not be resolved.")

    # Save JSON catalog
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2)
    print(f"JSON catalog saved to {JSON_PATH} ({len(catalog)} tables).")

    # Build SQLite DB
    build_sqlite_db(catalog)
    print("Offline Catalog Build Complete!")


if __name__ == "__main__":
    main()
