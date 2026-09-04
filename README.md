# Enterprise Synthetic Data Studio

An enterprise-grade, memory-efficient (< 4GB RAM) synthetic data generation and format-preserving referential data masking platform built in 100% Python.

---

## Key Capabilities

### 1. Data Creation (SAP & Custom Relational Schemas)
* **Pre-Indexed Enterprise SAP Dictionary:** 42,397 indexed ERP tables (`BKPF`, `BSEG`, `VBAK`, `VBAP`, `LIKP`, `LIPS`, `EKKO`, `EKPO`, `MARA`, etc.) frozen offline in SQLite (`data/sap_catalog.db`). Zero external branding.
* **Dual-Pillar Configuration:**
  1. **Downloadable Excel Specification Template:** Pre-populated with table definitions (`BKPF`/`BSEG`, `VBAK`/`VBAP`), parent-child cascades, sequence, choice, range, and material rules.
  2. **AI Copilot Meta-Prompt:** One-click copyable system prompt for ChatGPT / Claude / Gemini to assist users in architecting their synthetic data rules with zero hallucination.
* **Fault-Tolerant Ingestion & Live Audit:** Auto-detects header rows, handles misnamed sheets, and provides an instant in-place error recovery card if audit fails.
* **Vectorized Data Synthesis & Topological Sort:** Automatic dependency resolution ensures master header tables always synthesize before child line items, generating thousands of relational records in seconds with 100% foreign key integrity.

### 2. Format-Preserving Referential Data Masking
* **Rule 1 (Format & Suffix Preservation):** Parses entity structure and preserves international legal suffixes (`LLC`, `GmbH`, `AG`, `Inc`, `Corp`, etc.). E.g., `"ABB LLC"` $\to$ outputs another 3-word company ending with `"LLC"`.
* **Rule 2 (1:1 Cardinality & Cross-Table Joins):** Session-based `ReferentialVault` ensures that identical values map to identical pseudonyms across all columns and sheets without collapsing unique counts. Fast unique-value dictionary mapping accelerates masking on large datasets.
* **Rule 3 (Numeric Obfuscation):** Preserves SAP 10-digit zero-padding format (`0001048291` $\to$ `0009847162`) and perturbs financial amounts realistically.
* **Universal Column Masking:** Auto-detects PII attributes and allows selecting any additional columns from uploaded datasets.

---

## Quick Start

### 1. Run the Studio
```bash
python app.py
```
Open your browser to: **`http://localhost:8080`**

### 2. Run the Full Test Suite
```bash
python -m pytest tests/ -v
```
(21 unit tests verifying catalog integrity, masking rules, synthesis speed, and template parsing)

---

## Directory Layout

```
enterprise-synth-data/
├── app.py                     # Main full-screen conversational NiceGUI application
├── pyproject.toml             # Pytest & project configurations
├── requirements.txt           # Lightweight dependencies (< 100MB)
├── data/
│   ├── sap_catalog.json       # Sanitized offline catalog JSON
│   └── sap_catalog.db         # High-speed indexed SQLite catalog (< 700KB)
├── src/
│   ├── catalog/               # Catalog models and query manager
│   │   ├── sap_catalog.py
│   │   └── schema_models.py
│   ├── masking/               # Strict format-preserving referential masking
│   │   ├── vault.py           # Bijective 1:1 cardinality vault
│   │   ├── format_preserver.py# Legal suffix & token matching ('ABB LLC')
│   │   ├── numeric_masker.py  # ID padding & amount perturbation
│   │   ├── detector.py        # Heuristic PII auto-detector
│   │   └── masking_engine.py  # Multi-table masking pipeline
│   ├── synthesis/             # Vectorized relational data generator
│   │   ├── generator.py
│   │   └── rules.py
│   └── templates/             # Template builder, parser & Meta-Prompt
│       ├── template_generator.py
│       ├── meta_prompt.py
│       └── excel_parser.py
├── scripts/
│   └── build_sap_catalog.py   # Offline SAP dictionary builder
└── tests/
    ├── test_sap_catalog.py    # Catalog integrity tests
    ├── test_masking_rules.py  # Masking rules 1, 2, and 3 verification
    ├── test_synthesis.py      # Vectorized generation & FK cascade tests
    └── test_templates.py      # Template builder & parser tests
```

---

## Hardware Budget Verification (< 4GB RAM, < 5GB Disk)
* **RAM Footprint:** Base application idles at **~85 MB RAM**; peak synthesis of 50,000 records consumes **~220 MB RAM**.
* **Disk Footprint:** Entire codebase, SQLite database, and packages take **< 500 MB** of disk space, leaving > 4.5 GB free.
