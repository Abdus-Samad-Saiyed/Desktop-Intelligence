# Desktop Intelligence Plan v3 / v4 Implementation Ledger

Status as of Phase 0 baseline audit (2026-10-20).

## Legend
- **DONE**: Fully implemented, verified with strict tests that fail if reverted.
- **PARTIAL**: Partially implemented; requires refinement or has newly diagnosed defects.
- **TODO**: Not yet implemented or needs full overhaul in subsequent phases.

---

## 1. Plan v3 Sections 1.1 & 1.2: Core Defects & Invariants

| Item | Requirement | Status | Evidence (File & Line) | Proving Test |
|---|---|---|---|---|
| 1.1.A | WMI access denied handled gracefully with fallback and diagnostics | DONE | `desktop_intelligence/collectors/windows_process_events.py`, `collectors/wmi_errors.py`, `ui/health_summary.py`, `ui/pages/overview.py` (Why button), `ui/pages/health.py` | `tests/unit/test_stage1_wmi_resilience.py`, `tests/unit/test_v4_collector_status.py`, `tests/live/test_live_collector_pipeline.py` |
| 1.1.B | Overview dashboard repeated refresh C++ object deletion crash | DONE | `desktop_intelligence/ui/pages/overview.py:226-244` (`_clear_recommendations` preserves static labels, deletes only dynamic widgets) | `tests/unit/test_stage2_overview_lifecycle.py:test_overview_page_repeated_refreshes_across_all_transitions` |
| 1.1.C | Matplotlib singular transformation warning | DONE | `desktop_intelligence/visualization/charts.py:112` (`upper_limit = max(1.0, max_usage * 1.15)`) | `tests/unit/test_stage6_inventory_and_analytics.py:test_matplotlib_zero_usage_no_singular_transformation_warning` |
| 1.2.1 | `setup.py` bootstrapper SHA-256 byte-for-byte preserved | DONE | `setup.py:1` (Hash: `35320E317761EF4507DBA4566D7E654F6C1680E6040BDD1CCF36B2D1FA32664D`) | `tests/test_invariants.py:test_setup_py_hash_preserved` |
| 1.2.2 | `requirements.txt` strict 1 importable package per line (7 pkgs) | DONE | `requirements.txt:1-7` (7 non-empty lines, importable names) | `tests/test_invariants.py:test_requirements_format_and_importability` |
| 1.2.3 | Event-driven architecture (no polling <60s except WMI fallback) | DONE | `desktop_intelligence/collectors/foreground_events.py:12` (`SetWinEventHook`), `activity_manager.py:156` (60s idle heartbeat) | `tests/unit/test_stage1_storage_config.py:test_default_config_loads_all_fields` |
| 1.2.4 | Local-first CSV historical records with explicit UTC ISO timestamp | DONE | `desktop_intelligence/models.py:30-45` (`ISO_UTC_REGEX`), `csv_store.py:1` | `tests/test_invariants.py:test_utc_iso_timestamp_invariants` |
| 1.2.5 | Tracked repo `config.toml` pristine, user changes redirect to AppData | DONE | `desktop_intelligence/paths.py:33-40` (`base_dir / "config.toml"`) | `tests/test_invariants.py:test_default_config_invariants` |

---

## 2. Plan v3 Section 9: Visual Polish, High-DPI & Reliability Events

| Item | Requirement | Status | Evidence (File & Line) | Proving Test |
|---|---|---|---|---|
| 9.1.1 | Chart High-DPI canvas fill ratio (1.00 at 125%, 150%, 200%) | PARTIAL | `desktop_intelligence/visualization/charts.py:277-318` (geometry needs Phase 1 A.1 refactoring) | `tests/unit/test_stage8_ui_correctness.py:test_themed_chart_canvas_geometry_and_dpi_synchronization` (needs Phase 1 ratio tests) |
| 9.1.2 | Constrained layout for figures (no `tight_layout()`) | TODO | `desktop_intelligence/visualization/charts.py:137,273` (still has `fig.tight_layout()`) | Phase 1: `test_no_tight_layout_in_charts` |
| 9.1.3 | Transparent chart surfaces matching cards | TODO | `desktop_intelligence/visualization/charts.py:286` (`background-color: transparent`, but patches have default opacity) | Phase 1: `test_canvas_fills_card` |
| 9.2 | Durations as hours and minutes (no decimal hours) | DONE | `desktop_intelligence/formatting.py`, `ui/pages/overview.py:281`, `ui/pages/usage.py:121`, `charts.py` | `tests/unit/test_v4_formatting.py:test_format_duration_cases, test_usage_table_duration_item_sorting, test_no_decimal_hours_in_ui` |
| 9.3 | Reliability events parsed from real Event Log XML | DONE | `desktop_intelligence/collectors/system_errors.py:200-300` (`EvtQuery` + `EvtRender` XML parsing with `xml.etree`) | `tests/unit/test_stage4_reliability_events.py:test_parse_event_xml_*` |
| 9.4 | Single-flight DataLoaderWorker and Qt thread cleanup | DONE | `desktop_intelligence/ui/main_window.py:334-350` (`_active_worker`, `_refresh_pending`, `deleteLater`) | `tests/unit/test_stage8_ui_correctness.py:test_main_window_single_flight_worker` |
| 9.5 | Glassmorphism design tokens & WCAG AA accessible contrast | DONE | `desktop_intelligence/ui/theme.py:23-38,333-339` (`get_contrast_text_color`) | `tests/unit/test_stage8_ui_correctness.py:test_accent_presets_and_contrast_wcag_compliance` |

---

## 3. Plan v3 Section 10: Data Truth, Inventory & Observations

| Item | Requirement | Status | Evidence (File & Line) | Proving Test |
|---|---|---|---|---|
| 10.A | Inventory launch counting from process_start only | DONE | `desktop_intelligence/app.py:240-275` (counts strictly from `process_start` events) | `tests/unit/test_v4_data_truth.py:test_inventory_launch_counts_only_from_process_start` |
| 10.B | Resource hog observations vs exceedances | DONE | `desktop_intelligence/analytics/resources.py:11-70`, `ui/pages/health.py:155` | `tests/unit/test_v4_data_truth.py:test_resource_hogs_time_span_and_exceedance_separation` |
| 10.C | Explorer window noise diagnosis & transient filtering | DONE | `desktop_intelligence/collectors/foreground_events.py:75-140`, `activity_manager.py:255-270`, `scripts/diagnose_foreground.py` | `tests/unit/test_v4_data_truth.py:test_transient_shell_noise_filtering` |
| 10.D | Recommendation dismissals cooldown (`rejected` status) | DONE | `desktop_intelligence/analytics/recommendations.py:44-55` (`rejected` status cooldown) | `tests/unit/test_v4_data_truth.py:test_recommendation_dismissal_rejection_cooldown` |

---

## 4. Plan v3 Section 11: Deterministic Demo Mode

| Item | Requirement | Status | Evidence (File & Line) | Proving Test |
|---|---|---|---|---|
| 11.1 | `--demo-mode` CLI argument and isolated temporary storage | TODO | `desktop_intelligence/app.py` (not yet implemented) | Phase 6: `test_demo_mode_isolated_storage` |
| 11.2 | Deterministic seed data exercising all duration formats and edge cases | TODO | `scripts/` (needs demo seed script) | Phase 6: `test_demo_mode_manifest_assertions` |
| 11.3 | Visible Demo Mode UI banner and launch protection | TODO | `desktop_intelligence/ui/main_window.py` (not yet implemented) | Phase 6: `test_demo_mode_ui_banner` |

---

## 5. Plan v3 Section 12: Automation Modes & Thread-Safe Consent

| Item | Requirement | Status | Evidence (File & Line) | Proving Test |
|---|---|---|---|---|
| 12.1 | Automation modes (off, prompt, auto, notify) & config migration | PARTIAL | `desktop_intelligence/config.py:45` (`enabled = false`, `require_rule_approval`) | Phase 7: `test_automation_modes_config_migration` |
| 12.2 | Thread-safe `ConsentBroker` on GUI thread with signals & futures | PARTIAL | `desktop_intelligence/app.py:440` (lambda directly triggers dialog) | Phase 7: `test_consent_broker_thread_safety` |
| 12.3 | Headless `--collector-only` refusal to launch without consent channel | TODO | `desktop_intelligence/automation/scheduler.py` | Phase 7: `test_headless_collector_skips_without_consent_channel` |

---

## 6. Plan v3 Section 13: Daemon, Attach & Sign-in Startup

| Item | Requirement | Status | Evidence (File & Line) | Proving Test |
|---|---|---|---|---|
| 13.1 | Dual mutexes (`Local\DesktopIntelligence_Collector` & `UI`) | PARTIAL | `desktop_intelligence/app.py:348` (single mutex `Local\DesktopIntelligence_SingleInstance_Mutex`) | Phase 8: `test_dual_mutex_collector_and_ui` |
| 13.2 | GUI attach to running daemon via `daemon_status.json` | TODO | `desktop_intelligence/app.py` | Phase 8: `test_ui_attaches_to_running_daemon` |
| 13.3 | Sign-in startup toggle via HKCU Run key and `pythonw.exe` | TODO | `desktop_intelligence/ui/pages/settings.py` | Phase 8: `test_startup_run_key_toggle` |
| 13.4 | Headless consent prompt helper process (`--consent-prompt`) | TODO | `desktop_intelligence/app.py` | Phase 8: `test_headless_consent_prompt_helper` |
