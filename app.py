"""
Enterprise Synthetic Data Studio.
Modern, high-performance web studio built with NiceGUI.
Features tabbed workspace navigation, interactive 3-step synthesis canvas,
real-time audit diagnostics, format-preserving masking, and an embedded 42k SAP dictionary.
"""
import os
import io
import tempfile
import uuid
import pandas as pd
from nicegui import ui

from src.catalog.sap_catalog import SAPCatalogManager
from src.templates.template_generator import ExcelTemplateBuilder
from src.templates.meta_prompt import MetaPromptGenerator
from src.templates.excel_parser import FaultTolerantExcelParser
from src.synthesis import DataSynthesizer, sort_specs_topologically
from src.masking.masking_engine import DataMaskingEngine


# Initialize core backend engines
catalog = SAPCatalogManager()
template_builder = ExcelTemplateBuilder(catalog)
excel_parser = FaultTolerantExcelParser(catalog)
synthesizer = DataSynthesizer(catalog)
masking_engine = DataMaskingEngine()

TEMP_DIR = os.path.join(tempfile.gettempdir(), "enterprise_synth")
os.makedirs(TEMP_DIR, exist_ok=True)


class StudioState:
    """Session-isolated reactive state for the Enterprise Studio (DEF-01)."""
    def __init__(self):
        self.domain = "SAP"
        self.creation_specs = {}
        self.creation_dfs = {}
        self.uploaded_mask_tables = {}
        self.audit_report = None


def trigger_download(file_path: str, file_name: str):
    """Reliably sends bytes directly to the browser for instant download."""
    if os.path.exists(file_path):
        with open(file_path, "rb") as f:
            data = f.read()
        ui.download(data, filename=file_name)
    else:
        ui.notify(f"File '{file_name}' not found for download.", type="warning", position="top")


# ---------------------------------------------------------------------------
# MAIN PAGE LAYOUT: ENTERPRISE STUDIO WORKSPACE
# ---------------------------------------------------------------------------
@ui.page("/")
def main_page():
    # Session-isolated state & workspace directory per client connection (DEF-01, DEF-14)
    state = StudioState()
    session_id = uuid.uuid4().hex[:8]
    session_dir = os.path.join(TEMP_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    ui.add_head_html("""
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                background-color: #0B0F19;
                color: #F1F5F9;
            }
            .studio-card {
                background: #131B2E;
                border: 1px solid #1E293B;
                border-radius: 0.875rem;
                transition: border-color 0.2s ease, box-shadow 0.2s ease;
            }
            .studio-card:hover {
                border-color: #334155;
            }
            .studio-card-active {
                background: #141E36;
                border: 1px solid #6366F1;
                box-shadow: 0 0 20px rgba(99, 102, 241, 0.15);
            }
            .pill-btn {
                transition: all 0.18s ease-in-out;
            }
            .pill-btn:hover {
                transform: translateY(-1px);
                box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35);
            }
            .ag-theme-alpine-dark {
                --ag-background-color: #0F172A;
                --ag-header-background-color: #1E293B;
                --ag-odd-row-background-color: #111C33;
                --ag-border-color: #334155;
            }
        </style>
    """)

    # Top Brand Navigation Header
    with ui.header().classes("w-full bg-slate-900/90 backdrop-blur border-b border-slate-800 px-6 py-3 items-center justify-between shadow-lg sticky top-0 z-50"):
        with ui.row().classes("items-center gap-3"):
            ui.icon("bolt", size="sm").classes("text-indigo-400 animate-pulse")
            with ui.column().classes("gap-0"):
                ui.label("Enterprise Synth Studio").classes("text-lg font-extrabold text-white tracking-wide")
                ui.label("Vectorized Synthesis & Strict Format-Preserving Masking").classes("text-[11px] text-slate-400")
            ui.badge("v2.0", color="indigo").classes("text-[10px] ml-1 px-2 font-mono")

        # Workspace Navigation Tabs
        with ui.tabs().classes("text-slate-300") as main_tabs:
            tab_synthesis = ui.tab("🏭 Schema Studio & Synthesis", icon="auto_awesome").classes("font-semibold text-xs")
            tab_masking = ui.tab("🛡️ Data Masking Studio", icon="security").classes("font-semibold text-xs")
            tab_catalog = ui.tab("📖 SAP Data Dictionary", icon="menu_book").classes("font-semibold text-xs")

        with ui.row().classes("items-center gap-2"):
            with ui.row().classes("items-center gap-1.5 px-3 py-1 bg-emerald-950/50 border border-emerald-800/60 rounded-full"):
                ui.element("div").classes("w-2 h-2 rounded-full bg-emerald-400 animate-ping")
                ui.label("Engine Online").classes("text-[11px] font-semibold text-emerald-300")
            ui.button(icon="refresh", on_click=lambda: reset_entire_workspace()).props("flat round dense color=grey").tooltip("Reset Entire Workspace")

    # Main Workspace Body
    with ui.tab_panels(main_tabs, value=tab_synthesis).classes("w-full max-w-7xl mx-auto p-6 bg-transparent"):

        # ===================================================================
        # TAB 1: SCHEMA STUDIO & VECTORIZED SYNTHESIS
        # ===================================================================
        with ui.tab_panel(tab_synthesis).classes("p-0 gap-6 flex flex-col"):

            # Step Progress Ribbon
            with ui.row().classes("w-full items-center justify-between px-6 py-3 bg-slate-900/80 border border-slate-800 rounded-xl"):
                with ui.row().classes("items-center gap-3"):
                    ui.badge("Step 1", color="indigo").classes("font-mono text-xs")
                    ui.label("Domain & AI Copilot").classes("text-sm font-bold text-white")
                ui.icon("arrow_forward", size="xs").classes("text-slate-600")
                with ui.row().classes("items-center gap-3"):
                    ui.badge("Step 2", color="indigo").classes("font-mono text-xs")
                    ui.label("Specification & Live Audit").classes("text-sm font-bold text-white")
                ui.icon("arrow_forward", size="xs").classes("text-slate-600")
                with ui.row().classes("items-center gap-3"):
                    ui.badge("Step 3", color="emerald").classes("font-mono text-xs")
                    ui.label("Inspection & Full Generation").classes("text-sm font-bold text-emerald-400")

            # -------------------------------------------------------------
            # STEP 1: DOMAIN SELECTION & COPILOT ACTION CARDS
            # -------------------------------------------------------------
            with ui.card().classes("studio-card p-6 w-full gap-4"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column().classes("gap-0"):
                        ui.label("1. Target Schema Domain & Specification Model").classes("text-base font-bold text-white")
                        ui.label("Choose your enterprise architecture. Download the pre-formatted Excel template or use the AI Copilot to construct custom rules.").classes("text-xs text-slate-400")
                    
                    # Domain Selector Pills
                    with ui.row().classes("gap-2 bg-slate-900 p-1.5 rounded-xl border border-slate-800"):
                        btn_sap = ui.button("🏢 SAP Enterprise ERP", on_click=lambda: change_domain("SAP")).props("dense font-semibold").classes("text-xs px-4 rounded-lg")
                        btn_custom = ui.button("🛠️ Custom Schema", on_click=lambda: change_domain("CUSTOM")).props("dense font-semibold").classes("text-xs px-4 rounded-lg")

                def update_domain_pill_styles():
                    if state.domain == "SAP":
                        btn_sap.props("color=indigo")
                        btn_custom.props("flat color=grey")
                    else:
                        btn_sap.props("flat color=grey")
                        btn_custom.props("color=indigo")

                update_domain_pill_styles()

                def change_domain(new_domain: str):
                    state.domain = new_domain
                    update_domain_pill_styles()
                    ui.notify(f"Switched domain to {'SAP Enterprise ERP' if new_domain == 'SAP' else 'Custom Schema'}", type="info", position="top")

                # Action Cards Grid
                with ui.grid(columns=2).classes("w-full gap-4 mt-1"):
                    # Card A: Download Excel Specification Template
                    with ui.card().classes("p-5 bg-slate-900/90 border border-slate-800 rounded-xl justify-between flex flex-col"):
                        with ui.column().classes("gap-1"):
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("table_view", color="indigo").classes("text-base")
                                ui.label("Specification Template (.xlsx)").classes("font-bold text-white text-sm")
                            ui.label("Contains pre-configured 'Table_Definitions' and 'Field_Rules' sheets ready for immediate synthesis.").classes("text-xs text-slate-400 leading-relaxed")

                        def download_current_template():
                            tpl_file = os.path.join(session_dir, f"{state.domain}_Data_Spec_Template.xlsx")
                            template_builder.generate_template(tpl_file, domain=state.domain)
                            trigger_download(tpl_file, f"{state.domain}_Data_Spec_Template.xlsx")
                            ui.notify(f"Downloading {state.domain} template...", type="positive", position="top")

                        ui.button("📥 Download Excel Template", icon="download", on_click=download_current_template).props("color=indigo dense").classes("pill-btn rounded-lg mt-4 w-full font-semibold text-xs py-2")

                    # Card B: AI Copilot Prompt (Copy & View Modal)
                    with ui.card().classes("p-5 bg-slate-900/90 border border-slate-800 rounded-xl justify-between flex flex-col"):
                        with ui.column().classes("gap-1"):
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("psychology", color="indigo").classes("text-base")
                                ui.label("AI Copilot Meta-Prompt").classes("font-bold text-white text-sm")
                            ui.label("Paste this high-intensity zero-drift prompt into ChatGPT, Claude, or Gemini to automatically generate complete rule tables.").classes("text-xs text-slate-400 leading-relaxed")

                        def get_current_meta_prompt():
                            return MetaPromptGenerator.get_sap_meta_prompt() if state.domain == "SAP" else MetaPromptGenerator.get_custom_meta_prompt()

                        def copy_meta_prompt():
                            prompt_text = get_current_meta_prompt()
                            ui.clipboard.write(prompt_text)
                            ui.notify("Meta-Prompt copied to clipboard!", type="positive", position="top", icon="content_copy")

                        def open_prompt_modal():
                            prompt_text = get_current_meta_prompt()
                            with ui.dialog() as prompt_dlg, ui.card().classes("w-[800px] max-w-full p-6 bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl"):
                                with ui.row().classes("w-full items-center justify-between border-b border-slate-800 pb-3"):
                                    with ui.row().classes("items-center gap-2"):
                                        ui.icon("psychology", color="indigo")
                                        ui.label(f"AI Copilot System Prompt ({state.domain} Mode)").classes("font-bold text-base text-white")
                                    ui.button(icon="close", on_click=prompt_dlg.close).props("flat round dense")

                                ui.label("Paste this into your AI conversation alongside your business requirements:").classes("text-xs text-slate-400 mt-2 mb-2")
                                ui.textarea(value=prompt_text).props("readonly outlined").classes("w-full h-80 font-mono text-xs bg-slate-950 text-slate-200")

                                with ui.row().classes("w-full justify-between items-center mt-3"):
                                    ui.label("Tip: The prompt enforces strict 4-stage Markdown tables with referential keys.").classes("text-xs text-slate-500 italic")
                                    with ui.row().classes("gap-2"):
                                        ui.button("Copy Prompt", icon="content_copy", on_click=copy_meta_prompt).props("color=indigo dense").classes("text-xs")
                                        ui.button("Close", on_click=prompt_dlg.close).props("flat color=grey dense").classes("text-xs")
                            prompt_dlg.open()

                        with ui.row().classes("w-full gap-2 mt-4"):
                            ui.button("📋 Copy AI Prompt", icon="content_copy", on_click=copy_meta_prompt).props("color=indigo dense").classes("pill-btn flex-1 rounded-lg font-semibold text-xs py-2")
                            ui.button("View Prompt", icon="visibility", on_click=open_prompt_modal).props("outline color=indigo dense").classes("rounded-lg text-xs")

            # -------------------------------------------------------------
            # STEP 2: SPECIFICATION UPLOAD & LIVE AUDIT REPORT
            # -------------------------------------------------------------
            with ui.card().classes("studio-card p-6 w-full gap-4"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column().classes("gap-0"):
                        ui.label("2. Specification File Ingestion & Real-Time Audit").classes("text-base font-bold text-white")
                        ui.label("Drop your configured .xlsx specification. The engine will instantly audit table relations, rule syntax, and cascades.").classes("text-xs text-slate-400")

                    ui.button("🔄 Reset / Clear Uploader", icon="refresh", on_click=lambda: reset_spec_uploader()).props("flat dense color=indigo").classes("text-xs")

                # Uploader Container Slot
                upload_slot = ui.column().classes("w-full")
                audit_result_slot = ui.column().classes("w-full")
                spec_uploader = None

                def reset_spec_uploader():
                    nonlocal spec_uploader
                    if spec_uploader:
                        try:
                            spec_uploader.reset()
                        except Exception:
                            pass
                    audit_result_slot.clear()
                    state.creation_specs = {}
                    state.creation_dfs = {}
                    preview_slot.clear()
                    ui.notify("Uploader cleared. Ready for new specification.", type="info", position="top")

                async def process_spec_file(event):
                    try:
                        ui.notify("Reading uploaded specification...", type="info", position="top")
                        file_name = getattr(event, "name", None)
                        if not file_name and hasattr(event, "file") and event.file:
                            file_name = getattr(event.file, "name", "spec.xlsx")
                        file_name = file_name or "spec.xlsx"

                        if hasattr(event, "file") and event.file is not None:
                            content_bytes = await event.file.read()
                        elif hasattr(event, "content") and event.content is not None:
                            content_bytes = event.content.read()
                        else:
                            ui.notify("Could not read file payload.", type="negative", position="top")
                            return

                        # Native Quasar reset - clears the queue cleanly without destroying DOM
                        try:
                            event.sender.reset()
                        except Exception:
                            pass

                        specs, audit = excel_parser.parse_workbook(io.BytesIO(content_bytes))
                        state.audit_report = audit

                        audit_result_slot.clear()
                        with audit_result_slot:
                            if not audit["valid"]:
                                # Audit Failure Card
                                tpl_file = os.path.join(session_dir, f"{state.domain}_Data_Spec_Template.xlsx")
                                with ui.card().classes("p-5 w-full bg-rose-950/40 border border-rose-800/70 rounded-xl shadow-xl gap-3"):
                                    with ui.row().classes("w-full items-center justify-between"):
                                        with ui.row().classes("items-center gap-2"):
                                            ui.icon("error", color="rose").classes("text-lg")
                                            ui.label(f"⚠️ Specification Audit Failed for '{file_name}'").classes("font-bold text-rose-300 text-sm")
                                        ui.badge("Action Required", color="rose").classes("text-xs font-mono")

                                    ui.label("The parser could not locate valid table configurations or rule columns in this workbook:").classes("text-xs text-slate-300")

                                    with ui.column().classes("gap-1 text-xs text-rose-200 font-mono bg-slate-950/80 p-3 rounded-lg border border-rose-900/50 w-full"):
                                        for w in audit.get("warnings", []):
                                            ui.label(f"• {w}")
                                        if audit.get("sheets_found"):
                                            ui.label(f"• Sheets detected: {', '.join(audit['sheets_found'])}").classes("text-slate-400")

                                    with ui.row().classes("w-full gap-3 mt-1"):
                                        ui.button("🔄 Try Again", icon="refresh", on_click=reset_spec_uploader).props("color=rose dense").classes("pill-btn rounded-lg text-xs font-semibold px-4 py-2")
                                        ui.button("📥 Download Fresh Template", icon="download", on_click=lambda: trigger_download(tpl_file, f"{state.domain}_Data_Spec_Template.xlsx")).props("outline color=white dense").classes("rounded-lg text-xs px-3")
                                return

                            # Audit Success Card
                            state.creation_specs = specs
                            ui.notify(f"Successfully audited {len(specs)} table(s) from '{file_name}'!", type="positive", position="top")

                            with ui.card().classes("p-5 w-full bg-emerald-950/30 border border-emerald-800/60 rounded-xl shadow-xl gap-3"):
                                with ui.row().classes("w-full items-center justify-between"):
                                    with ui.row().classes("items-center gap-2"):
                                        ui.icon("check_circle", color="emerald").classes("text-lg")
                                        ui.label(f"✅ Specification Audited Successfully ({file_name})").classes("font-bold text-emerald-400 text-sm")
                                    ui.badge(f"{len(specs)} Tables Configured", color="emerald").classes("text-xs font-mono")

                                with ui.column().classes("gap-1 text-xs text-slate-300 font-mono bg-slate-950/70 p-3 rounded-lg border border-slate-800 w-full"):
                                    for t_name, spec in specs.items():
                                        parent_info = f" ➔ Cascaded from Header [{spec.parent_table}]" if spec.parent_table else " [Master Header Table]"
                                        ui.label(f"• {t_name:8s}: {spec.row_count} target rows | {len(spec.rules)} custom rules {parent_info}")

                                with ui.row().classes("w-full items-center justify-between mt-2 pt-2 border-t border-slate-800/80"):
                                    ui.button("👁️ Generate Live 5-Row Preview", icon="preview", on_click=lambda: execute_live_preview(state.creation_specs)).props("color=indigo").classes("pill-btn rounded-full px-6 font-bold py-2 shadow-lg")
                                    ui.button("🔄 Upload Different File", icon="upload_file", on_click=reset_spec_uploader).props("flat color=slate-400 dense").classes("text-xs hover:text-white")

                    except Exception as ex:
                        ui.notify(f"File Processing Error: {str(ex)}", type="negative", position="top")

                with upload_slot:
                    spec_uploader = ui.upload(
                        label="Drop completed .xlsx specification file here",
                        auto_upload=True,
                        on_upload=process_spec_file
                    ).props("accept=.xlsx,.xls max-files=1").classes("w-full bg-slate-900/60 rounded-xl border border-dashed border-slate-700 p-3")

            # -------------------------------------------------------------
            # STEP 3: INTERACTIVE INSPECTOR & FULL DATASET GENERATION
            # -------------------------------------------------------------
            preview_slot = ui.column().classes("w-full gap-4")

            def execute_live_preview(specs):
                try:
                    ui.notify("Executing vectorized synthesis for preview...", type="info", position="top")
                    ordered_specs = sort_specs_topologically(specs)
                    preview_dfs = {}
                    for t_name, spec in ordered_specs.items():
                        if spec.parent_table and spec.parent_table in preview_dfs:
                            child_df = synthesizer.generate_sap_table(
                                t_name,
                                custom_rules=spec.rules,
                                parent_df=preview_dfs[spec.parent_table]
                            )
                            preview_dfs[t_name] = child_df.head(5)
                        else:
                            parent_df = synthesizer.generate_sap_table(
                                t_name,
                                row_count=5,
                                custom_rules=spec.rules
                            )
                            preview_dfs[t_name] = parent_df

                    state.creation_dfs = preview_dfs

                    # Export sample preview file to session-isolated path (DEF-14)
                    sample_file = os.path.join(session_dir, "Sample_Data_Preview_5_Rows.xlsx")
                    with pd.ExcelWriter(sample_file, engine="openpyxl") as writer:
                        for t_name, p_df in preview_dfs.items():
                            p_df.to_excel(writer, sheet_name=t_name[:31], index=False)

                    preview_slot.clear()
                    with preview_slot:
                        with ui.card().classes("studio-card studio-card-active p-6 w-full gap-4"):
                            # Inspector Header Toolbar
                            with ui.row().classes("w-full items-center justify-between"):
                                with ui.column().classes("gap-0"):
                                    ui.label("3. Live Multi-Table Data Inspector").classes("text-base font-bold text-white")
                                    ui.label("All foreign key cascades, conversion exits (ALPHA), and domain values verified.").classes("text-xs text-slate-400")

                                with ui.row().classes("items-center gap-2"):
                                    ui.button("⬇️ Download Sample (.xlsx)", icon="download", on_click=lambda: trigger_download(sample_file, "Sample_Data_Preview_5_Rows.xlsx")).props("outline color=indigo dense").classes("pill-btn text-xs font-semibold px-3")
                                    ui.button("⛶ Fullscreen Inspector", icon="fullscreen", on_click=lambda: open_fullscreen_inspector(preview_dfs, sample_file)).props("flat color=indigo dense").classes("text-xs")

                            # Table Selection Tabs
                            with ui.tabs().classes("w-full text-indigo-400 border-b border-slate-800") as table_tabs:
                                tab_widgets = {t: ui.tab(f"{t} ({len(preview_dfs[t])} rows, {len(preview_dfs[t].columns)} cols)") for t in preview_dfs.keys()}

                            with ui.tab_panels(table_tabs, value=list(tab_widgets.values())[0]).classes("w-full bg-slate-950 p-3 rounded-xl border border-slate-800 overflow-hidden"):
                                for t_name, p_df in preview_dfs.items():
                                    with ui.tab_panel(tab_widgets[t_name]).classes("w-full p-0"):
                                        col_defs = [
                                            {"headerName": col, "field": col, "minWidth": 140, "sortable": True, "filter": True, "resizable": True}
                                            for col in p_df.columns
                                        ]
                                        ui.aggrid({
                                            "columnDefs": col_defs,
                                            "rowData": p_df.to_dict("records"),
                                            "defaultColDef": {"resizable": True, "minWidth": 140, "sortable": True, "filter": True},
                                            "pagination": False
                                        }).classes("w-full h-72 ag-theme-alpine-dark")

                            # Full Generation Callout & Trigger
                            total_target_rows = sum(spec.row_count for spec in specs.values())
                            with ui.row().classes("w-full items-center justify-between mt-3 p-4 bg-slate-900/90 border border-slate-800 rounded-xl"):
                                with ui.column().classes("gap-0"):
                                    ui.label(f"Ready for Full Synthesis: {total_target_rows:,} Total Target Records").classes("font-bold text-white text-sm")
                                    ui.label("Vectorized generation will stream into a multi-sheet Microsoft Excel workbook.").classes("text-xs text-slate-400")

                                ui.button("🚀 Generate Full Dataset & Download (.xlsx)", icon="rocket_launch", on_click=lambda: execute_full_synthesis(state.creation_specs)).props("color=emerald").classes("pill-btn rounded-full px-8 font-bold py-2.5 shadow-xl")

                except Exception as ex:
                    ui.notify(f"Synthesis Error: {str(ex)}", type="negative", position="top")

            def open_fullscreen_inspector(preview_dfs, sample_file):
                with ui.dialog() as fs_dlg, ui.card().classes("w-[95vw] max-w-7xl h-[85vh] p-6 bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl flex flex-col"):
                    with ui.row().classes("w-full items-center justify-between border-b border-slate-800 pb-3"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("table_chart", color="indigo")
                            ui.label("Fullscreen Multi-Table Schema Inspector").classes("font-bold text-lg text-white")
                        with ui.row().classes("gap-2"):
                            ui.button("Download Sample (.xlsx)", icon="download", on_click=lambda: trigger_download(sample_file, "Sample_Data_Preview_5_Rows.xlsx")).props("outline color=indigo dense").classes("text-xs")
                            ui.button(icon="close", on_click=fs_dlg.close).props("flat round dense")

                    with ui.tabs().classes("w-full text-indigo-400 mt-2") as fs_tabs:
                        fs_tab_objs = {t: ui.tab(f"{t} ({len(preview_dfs[t].columns)} Columns)") for t in preview_dfs.keys()}

                    with ui.tab_panels(fs_tabs, value=list(fs_tab_objs.values())[0]).classes("w-full flex-1 bg-slate-950 rounded-xl p-3 border border-slate-800 overflow-hidden"):
                        for t_name, p_df in preview_dfs.items():
                            with ui.tab_panel(fs_tab_objs[t_name]).classes("w-full h-full p-0"):
                                col_defs = [{"headerName": col, "field": col, "minWidth": 140, "sortable": True, "filter": True, "resizable": True} for col in p_df.columns]
                                ui.aggrid({
                                    "columnDefs": col_defs,
                                    "rowData": p_df.to_dict("records"),
                                    "defaultColDef": {"resizable": True, "minWidth": 140}
                                }).classes("w-full h-[62vh] ag-theme-alpine-dark")
                fs_dlg.open()

            def execute_full_synthesis(specs):
                try:
                    ui.notify("Executing full vectorized dataset synthesis...", type="info", position="top")
                    ordered_specs = sort_specs_topologically(specs)
                    full_dfs = {}
                    for t_name, spec in ordered_specs.items():
                        if spec.parent_table and spec.parent_table in full_dfs:
                            child_df = synthesizer.generate_sap_table(
                                t_name,
                                custom_rules=spec.rules,
                                parent_df=full_dfs[spec.parent_table]
                            )
                            full_dfs[t_name] = child_df
                        else:
                            parent_df = synthesizer.generate_sap_table(
                                t_name,
                                row_count=spec.row_count,
                                custom_rules=spec.rules
                            )
                            full_dfs[t_name] = parent_df

                    out_path = os.path.join(session_dir, f"{state.domain}_Synthesized_Full_Dataset.xlsx")
                    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
                        for t_name, df_out in full_dfs.items():
                            df_out.to_excel(writer, sheet_name=t_name[:31], index=False)

                    total_rows = sum(len(d) for d in full_dfs.values())
                    ui.notify(f"Successfully synthesized {total_rows:,} records across {len(full_dfs)} tables!", type="positive", position="top")
                    trigger_download(out_path, f"{state.domain}_Synthesized_Full_Dataset.xlsx")

                except Exception as ex:
                    ui.notify(f"Generation Error: {str(ex)}", type="negative", position="top")

        # ===================================================================
        # TAB 2: FORMAT-PRESERVING DATA MASKING STUDIO
        # ===================================================================
        with ui.tab_panel(tab_masking).classes("p-0 gap-6 flex flex-col"):

            with ui.card().classes("studio-card p-6 w-full gap-4"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column().classes("gap-0"):
                        ui.label("Enterprise Format-Preserving Data Sanitization").classes("text-base font-bold text-white")
                        ui.label("Enforces Rule 1 ('ABB LLC' ➔ 3-word company with LLC), Rule 2 (1:1 Referential Cardinality Vault), and Rule 3 (Numeric Obfuscation).").classes("text-xs text-slate-400")

                    ui.button("🔄 Reset / Clear Uploader", icon="refresh", on_click=lambda: reset_mask_uploader()).props("flat dense color=indigo").classes("text-xs")

                mask_upload_slot = ui.column().classes("w-full")
                mask_config_slot = ui.column().classes("w-full")
                mask_preview_slot = ui.column().classes("w-full")
                mask_uploader = None

                def reset_mask_uploader():
                    nonlocal mask_uploader
                    if mask_uploader:
                        try:
                            mask_uploader.reset()
                        except Exception:
                            pass
                    mask_config_slot.clear()
                    mask_preview_slot.clear()
                    state.uploaded_mask_tables = {}
                    ui.notify("Masking studio cleared. Ready for new dataset.", type="info", position="top")

                async def process_mask_upload(event):
                    try:
                        ui.notify("Ingesting dataset for sanitization...", type="info", position="top")
                        file_name = getattr(event, "name", None)
                        if not file_name and hasattr(event, "file") and event.file:
                            file_name = getattr(event.file, "name", "dataset.xlsx")
                        file_name = file_name or "dataset.xlsx"

                        if hasattr(event, "file") and event.file is not None:
                            content_bytes = await event.file.read()
                        elif hasattr(event, "content") and event.content is not None:
                            content_bytes = event.content.read()
                        else:
                            ui.notify("Could not read file payload.", type="negative", position="top")
                            return

                        try:
                            event.sender.reset()
                        except Exception:
                            pass

                        tables = {}
                        if file_name.lower().endswith(".csv"):
                            tables["Dataset"] = pd.read_csv(io.BytesIO(content_bytes))
                        else:
                            xls = pd.ExcelFile(io.BytesIO(content_bytes))
                            for s in xls.sheet_names:
                                tables[s] = pd.read_excel(xls, sheet_name=s)

                        state.uploaded_mask_tables = tables
                        ui.notify(f"Loaded {len(tables)} table(s) from '{file_name}'.", type="positive", position="top")
                        suggestions = masking_engine.detect_sensitive_columns(tables)
                        render_mask_configuration(tables, suggestions)

                    except Exception as ex:
                        ui.notify(f"Masking File Error: {str(ex)}", type="negative", position="top")

                def render_mask_configuration(tables, suggestions):
                    mask_config_slot.clear()
                    extra_select_widgets = {}
                    with mask_config_slot:
                        with ui.card().classes("p-5 w-full bg-slate-900 border border-slate-800 rounded-xl shadow-xl gap-3 mt-4"):
                            ui.label("2. Masking Configuration & PII Selection").classes("font-bold text-white text-sm")
                            ui.label("Review auto-detected PII or pick any additional columns. Bijective 1:1 mapping strictly preserves relational joins across all sheets.").classes("text-xs text-slate-400")

                            col_checkboxes = {}
                            for t_name, df_t in tables.items():
                                with ui.card().classes("p-3 w-full bg-slate-950 border border-slate-800 rounded-lg gap-2 mt-2"):
                                    ui.label(f"Table: {t_name} ({len(df_t)} rows, {len(df_t.columns)} cols)").classes("font-semibold text-xs text-indigo-400")
                                    
                                    t_sugs = suggestions.get(t_name, [])
                                    detected_cols = set()
                                    if t_sugs:
                                        for sug in t_sugs:
                                            detected_cols.add(sug['column'])
                                            col_key = f"{t_name}::{sug['column']}"
                                            cb = ui.checkbox(
                                                f"Mask '{sug['column']}' (Detected: {sug['category']}, Confidence: {sug['confidence']})",
                                                value=True
                                            ).classes("text-xs text-slate-200")
                                            col_checkboxes[col_key] = (t_name, sug['column'], sug['category'], cb)
                                    else:
                                        ui.label("No automatic PII flags detected.").classes("text-xs text-slate-500 italic")

                                    # Allow user to pick any additional columns from the table to mask (DEF-12: no monkey-patching)
                                    other_cols = [c for c in df_t.columns if c not in detected_cols]
                                    if other_cols:
                                        extra_select = ui.select(
                                            options=other_cols,
                                            label=f"Pick additional columns from {t_name} to mask",
                                            multiple=True
                                        ).classes("w-full text-xs")
                                        extra_select_widgets[t_name] = extra_select

                            # Optional Custom Company Pool
                            ui.label("Optional: Custom Replacement Company Pool").classes("font-bold text-sm text-white mt-2")
                            ui.label("Provide replacement names separated by commas (e.g. Apex Global LLC, Titan Dynamics Inc). 1:1 cardinality is strictly maintained.").classes("text-xs text-slate-400")
                            custom_input = ui.input(placeholder="Apex Global LLC, Titan Dynamics Inc, Zephyr Systems LLC").classes("w-full text-xs")

                            def apply_and_preview_mask():
                                configs = {}
                                for col_key, (t_name, c_name, cat, cb) in col_checkboxes.items():
                                    if cb.value:
                                        if t_name not in configs:
                                            configs[t_name] = {}
                                        configs[t_name][c_name] = cat

                                # Include extra user-selected columns cleanly from widgets (DEF-12)
                                for t_name, extra_sel in extra_select_widgets.items():
                                    if extra_sel.value:
                                        if t_name not in configs:
                                            configs[t_name] = {}
                                        for extra_col in extra_sel.value:
                                            configs[t_name][extra_col] = "company_name"

                                if not configs:
                                    ui.notify("Please select at least one column to mask.", type="warning", position="top")
                                    return

                                custom_pools = {}
                                if custom_input.value and custom_input.value.strip():
                                    names = [n.strip() for n in custom_input.value.split(",") if n.strip()]
                                    custom_pools["NAME1"] = names
                                    custom_pools["company_name"] = names

                                preview = masking_engine.generate_preview(tables, configs, custom_pools, preview_rows=5)
                                render_mask_preview_results(preview, tables, configs, custom_pools)

                            ui.button("⚡ Apply Format-Preserving Masking & Preview", icon="security", on_click=apply_and_preview_mask).props("color=indigo").classes("pill-btn rounded-full px-6 font-semibold mt-2")

                def render_mask_preview_results(preview, full_tables, configs, custom_pools):
                    sample_mask_file = os.path.join(session_dir, "Masked_Sample_Comparison.xlsx")
                    with pd.ExcelWriter(sample_mask_file, engine="openpyxl") as writer:
                        for t_name, pair in preview.items():
                            pair["original"].to_excel(writer, sheet_name=f"{t_name[:25]}_Orig", index=False)
                            pair["masked"].to_excel(writer, sheet_name=f"{t_name[:25]}_Mask", index=False)

                    mask_preview_slot.clear()
                    with mask_preview_slot:
                        with ui.card().classes("p-5 w-full bg-slate-900 border border-indigo-900/60 rounded-xl shadow-xl gap-4 mt-4"):
                            with ui.row().classes("w-full items-center justify-between"):
                                with ui.column().classes("gap-0"):
                                    ui.label("🛡️ Before vs After Masking Comparison (First 5 Rows)").classes("font-bold text-white text-sm")
                                    ui.label("Rule 1 (3-token + LLC), Rule 2 (1:1 Cardinality), and Rule 3 (Numeric Perturbation) applied.").classes("text-xs text-emerald-400")

                                ui.button("⬇️ Download Comparison Sample (.xlsx)", icon="download", on_click=lambda: trigger_download(sample_mask_file, "Masked_Sample_Comparison.xlsx")).props("outline color=indigo dense").classes("text-xs font-semibold")

                            for t_name, pair in preview.items():
                                ui.label(f"Table: {t_name}").classes("text-xs font-bold text-indigo-300 mt-2")
                                with ui.grid(columns=2).classes("w-full gap-3"):
                                    with ui.column().classes("bg-slate-950 p-3 rounded-lg border border-red-900/40"):
                                        ui.label("Original (Before)").classes("text-[11px] font-bold text-red-400 uppercase")
                                        ui.aggrid({
                                            "columnDefs": [{"headerName": c, "field": c, "minWidth": 120} for c in pair["original"].columns],
                                            "rowData": pair["original"].to_dict("records"),
                                            "defaultColDef": {"resizable": True, "minWidth": 120}
                                        }).classes("h-48 w-full ag-theme-alpine-dark")

                                    with ui.column().classes("bg-slate-950 p-3 rounded-lg border border-emerald-900/40"):
                                        ui.label("Masked (After)").classes("text-[11px] font-bold text-emerald-400 uppercase")
                                        ui.aggrid({
                                            "columnDefs": [{"headerName": c, "field": c, "minWidth": 120} for c in pair["masked"].columns],
                                            "rowData": pair["masked"].to_dict("records"),
                                            "defaultColDef": {"resizable": True, "minWidth": 120}
                                        }).classes("h-48 w-full ag-theme-alpine-dark")

                            def download_full_masked_dataset():
                                masked_full = masking_engine.mask_dataset(full_tables, configs, custom_pools)
                                out_path = os.path.join(session_dir, "Sanitized_Full_Dataset.xlsx")
                                with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
                                    for t_name, df_m in masked_full.items():
                                        df_m.to_excel(writer, sheet_name=t_name[:31], index=False)

                                total_rows = sum(len(d) for d in masked_full.values())
                                ui.notify(f"Sanitized {total_rows:,} records preserving 1:1 cardinality!", type="positive", position="top")
                                trigger_download(out_path, "Sanitized_Full_Dataset.xlsx")

                            ui.button("🚀 Export Full Sanitized Dataset (.xlsx)", icon="file_download", on_click=download_full_masked_dataset).props("color=emerald").classes("pill-btn rounded-full px-6 font-bold py-2 shadow-lg mt-2")

                with mask_upload_slot:
                    mask_uploader = ui.upload(
                        label="Drop dataset to sanitize (Excel .xlsx or CSV)",
                        auto_upload=True,
                        on_upload=process_mask_upload
                    ).props("accept=.xlsx,.xls,.csv max-files=1").classes("w-full bg-slate-900/60 rounded-xl border border-dashed border-slate-700 p-3")

        # ===================================================================
        # TAB 3: SAP DATA DICTIONARY EXPLORER (42,397 TABLES)
        # ===================================================================
        with ui.tab_panel(tab_catalog).classes("p-0 gap-6 flex flex-col"):

            with ui.card().classes("studio-card p-6 w-full gap-4"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column().classes("gap-0"):
                        ui.label("📖 Enterprise SAP Data Dictionary & Relationship Explorer").classes("text-base font-bold text-white")
                        ui.label("Search 42,397 indexed SAP tables, field specifications, ABAP conversion exits, and foreign key cascades.").classes("text-xs text-slate-400")

                    ui.badge("42,397 Tables Indexed", color="indigo").classes("text-xs font-mono px-2")

                search_input = ui.input(placeholder="Search table name or keyword (e.g. VBAK, LIKP, Billing, Material, BSEG)...").classes("w-full bg-slate-900 rounded-xl text-xs")
                results_container = ui.column().classes("w-full max-h-[65vh] overflow-y-auto gap-3 pr-2")

                def run_catalog_search():
                    results_container.clear()
                    q = search_input.value.strip()
                    if not q:
                        tables = catalog.list_tables()[:30]
                        with results_container:
                            ui.label(f"Core Enterprise Tables ({len(tables)} displayed of 42k)").classes("text-xs font-bold uppercase text-slate-400")
                            for t in tables:
                                with ui.expansion(f"{t['name']} - {t['description']}", icon="table_chart").classes("w-full bg-slate-900/80 rounded-xl border border-slate-800"):
                                    render_table_details(t["name"])
                        return

                    results = catalog.search(q)
                    with results_container:
                        if not results:
                            ui.label("No tables or fields matched your query.").classes("text-xs text-slate-400 italic")
                            return

                        ui.label(f"Found {len(results)} matching entity/entities:").classes("text-xs font-bold uppercase text-indigo-400")
                        for r in results:
                            if r.get("type") == "table":
                                with ui.expansion(f"Table {r['name']}: {r['description']} ({r['category']})", icon="table_chart").classes("w-full bg-slate-900 rounded-xl border border-slate-800"):
                                    render_table_details(r["name"])
                            else:
                                with ui.card().classes("w-full p-3 bg-slate-950 border border-slate-800 rounded-lg"):
                                    ui.label(f"Field {r['table']}.{r['name']} [{r['data_type']}]").classes("font-bold text-indigo-300 text-xs")
                                    ui.label(r["description"]).classes("text-xs text-slate-400")

                def render_table_details(table_name: str):
                    tbl_schema = catalog.get_table(table_name)
                    if tbl_schema:
                        with ui.column().classes("p-3 gap-2 w-full"):
                            ui.label(f"Category: {tbl_schema.category} | Primary Keys: {', '.join(tbl_schema.keys)}").classes("text-xs text-indigo-400 font-semibold")
                            if tbl_schema.foreign_keys:
                                fk_str = ", ".join([f"{fk.field} ➔ {fk.ref_table}.{fk.ref_field}" for fk in tbl_schema.foreign_keys])
                                ui.label(f"Foreign Key Joins: {fk_str}").classes("text-xs text-amber-400 font-mono")

                            # High-speed lightweight table preview (instant DOM render, 0 JS overhead)
                            f_list = list(tbl_schema.fields.values())
                            with ui.element("div").classes("w-full max-h-52 overflow-y-auto border border-slate-800 rounded-lg bg-slate-950"):
                                with ui.element("table").classes("w-full text-xs text-left text-slate-300"):
                                    with ui.element("thead").classes("text-[11px] uppercase bg-slate-900 text-slate-400 sticky top-0"):
                                        with ui.element("tr"):
                                            ui.element("th").classes("px-3 py-2").text = "Field"
                                            ui.element("th").classes("px-3 py-2").text = "Type"
                                            ui.element("th").classes("px-3 py-2").text = "Length"
                                            ui.element("th").classes("px-3 py-2").text = "Description"
                                    with ui.element("tbody"):
                                        for f in f_list[:30]:
                                            with ui.element("tr").classes("border-b border-slate-800/60 hover:bg-slate-900/50"):
                                                ui.element("td").classes("px-3 py-1.5 font-mono text-indigo-300 font-semibold").text = f.name
                                                ui.element("td").classes("px-3 py-1.5 font-mono text-slate-400").text = f.data_type
                                                ui.element("td").classes("px-3 py-1.5 font-mono text-slate-400").text = str(f.length)
                                                ui.element("td").classes("px-3 py-1.5 text-slate-300").text = f.description or ""

                search_timer = None
                def debounced_search():
                    nonlocal search_timer
                    if search_timer:
                        search_timer.cancel()
                    search_timer = ui.timer(0.25, run_catalog_search, once=True)

                search_input.on("input", debounced_search)
                run_catalog_search()

    def reset_entire_workspace():
        state.creation_specs = {}
        state.creation_dfs = {}
        state.uploaded_mask_tables = {}
        ui.notify("Entire Studio workspace reset.", type="info", position="top")
        ui.navigate.to("/")


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="Enterprise Synthetic Data Studio",
        port=8080,
        reload=False,
        show=False,
        dark=True
    )
