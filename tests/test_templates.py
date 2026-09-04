"""
Unit tests for Excel Template Generation, Fault-Tolerant Parsing, and Meta-Prompts.
"""
import os
import pytest
from src.templates.template_generator import ExcelTemplateBuilder
from src.templates.meta_prompt import MetaPromptGenerator
from src.templates.excel_parser import FaultTolerantExcelParser


@pytest.fixture
def tmp_excel_path(tmp_path):
    return str(tmp_path / "test_spec.xlsx")


def test_template_builder_creates_valid_file(tmp_excel_path):
    builder = ExcelTemplateBuilder()
    out = builder.generate_template(tmp_excel_path, domain="SAP")
    assert os.path.exists(out)
    assert os.path.getsize(out) > 2000


def test_meta_prompt_generation():
    prompt_sap = MetaPromptGenerator.get_sap_meta_prompt()
    assert "Table_Definitions" in prompt_sap
    assert "Field_Rules" in prompt_sap
    assert "BKPF" in prompt_sap
    assert "BUKRS" in prompt_sap
    assert "IMMUTABLE OPERATIONAL INVARIANTS" in prompt_sap
    assert "ZERO-DRIFT MANDATE" in prompt_sap
    assert "4-STAGE RESPONSE PROTOCOL" in prompt_sap

    prompt_custom = MetaPromptGenerator.get_custom_meta_prompt()
    assert "Customers" in prompt_custom
    assert "Orders" in prompt_custom
    assert "IMMUTABLE OPERATIONAL INVARIANTS" in prompt_custom


def test_fault_tolerant_parser_on_generated_template(tmp_excel_path):
    builder = ExcelTemplateBuilder()
    builder.generate_template(tmp_excel_path, domain="SAP")

    parser = FaultTolerantExcelParser()
    specs, audit = parser.parse_workbook(tmp_excel_path)

    assert audit["valid"] is True
    assert "BKPF" in specs
    assert specs["BKPF"].row_count == 500
    assert "BSEG" in specs
    assert specs["BSEG"].parent_table == "BKPF"
    
    # Check that rules were parsed
    bkpf_rules = specs["BKPF"].rules
    assert "BUKRS" in bkpf_rules
    assert bkpf_rules["BUKRS"].rule_type == "choice"
    assert "1000" in bkpf_rules["BUKRS"].parameters["choices"]
    assert bkpf_rules["BUKRS"].parameters["weights"][0] == 0.6
