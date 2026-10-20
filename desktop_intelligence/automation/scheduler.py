"""Automation scheduler managing rule triggering, consent behavior, and audit logging."""

from datetime import datetime, timezone
import logging
from typing import Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from desktop_intelligence.automation.launcher import BaseLauncher, SafeProcessLauncher
from desktop_intelligence.automation.rules import AutomationRule
from desktop_intelligence.collectors.base import Clock, SystemClock
from desktop_intelligence.config import AppConfig
from desktop_intelligence.models import AutomationLogRecord, format_utc_iso, new_id
from desktop_intelligence.storage.csv_store import CsvStore

logger = logging.getLogger(__name__)

ConsentCallback = Callable[[AutomationRule, int], str]  # returns "approve", "reject", or "timeout"


class AutomationScheduler:
    """Evaluates approved automation rules and executes scheduled launches."""

    def __init__(
        self,
        config: AppConfig,
        store: CsvStore,
        launcher: Optional[BaseLauncher] = None,
        clock: Optional[Clock] = None,
        consent_provider: Optional[ConsentCallback] = None,
    ):
        self.config = config
        self.store = store
        self.launcher = launcher or SafeProcessLauncher()
        self.clock = clock or SystemClock()
        self.consent_provider = consent_provider
        self.rules: List[AutomationRule] = []

    def set_rules(self, rules: List[AutomationRule]) -> None:
        self.rules = rules
        self._hydrate_last_triggered_dates()

    def _hydrate_last_triggered_dates(self) -> None:
        """Populate last_triggered_date for each rule from historical automation logs."""
        try:
            logs = self.store.read_rows("automation_log", self.store.paths.automation_log_csv)
            if not logs:
                return

            tz_str = self.config.general.timezone
            if tz_str.lower() == "utc":
                local_tz = timezone.utc
            elif tz_str.lower() == "local":
                local_tz = datetime.now().astimezone().tzinfo
            else:
                try:
                    local_tz = ZoneInfo(tz_str)
                except Exception:
                    local_tz = datetime.now().astimezone().tzinfo

            latest_dates: Dict[str, str] = {}
            for r in logs:
                rule_id = r.get("rule_id", "")
                ts_str = r.get("ts_utc", "")
                result = r.get("result", "")
                if rule_id and ts_str and result in {"success", "skipped_duplicate"}:
                    try:
                        from desktop_intelligence.models import parse_utc_iso
                        dt = parse_utc_iso(ts_str).astimezone(local_tz)
                        date_str = dt.strftime("%Y-%m-%d")
                        if rule_id not in latest_dates or date_str > latest_dates[rule_id]:
                            latest_dates[rule_id] = date_str
                    except Exception:
                        pass

            for rule in self.rules:
                if rule.rule_id in latest_dates and not rule.last_triggered_date:
                    rule.last_triggered_date = latest_dates[rule.rule_id]
        except Exception as exc:
            logger.debug("Failed hydrating last_triggered_dates: %s", exc)

    def evaluate_and_trigger(self) -> List[AutomationLogRecord]:
        """Evaluate all rules against current time and trigger eligible actions."""
        executed_logs: List[AutomationLogRecord] = []

        now_utc_dt = self.clock.now_utc()
        now_ts_str = format_utc_iso(now_utc_dt)

        # Determine current local date, day of week, and time bucket
        tz_str = self.config.general.timezone
        if tz_str.lower() == "utc":
            local_tz = timezone.utc
        elif tz_str.lower() == "local":
            local_tz = datetime.now().astimezone().tzinfo
        else:
            try:
                local_tz = ZoneInfo(tz_str)
            except Exception:
                local_tz = datetime.now().astimezone().tzinfo

        local_dt = now_utc_dt.astimezone(local_tz)
        local_date_str = local_dt.strftime("%Y-%m-%d")
        current_dow = local_dt.strftime("%A")
        bucket_mins = self.config.patterns.time_bucket_minutes
        b_minute = (local_dt.minute // bucket_mins) * bucket_mins
        current_time_bucket = f"{local_dt.hour:02d}:{b_minute:02d}"

        for rule in self.rules:
            # 1. Master automation enabled and mode check
            mode = getattr(self.config.automation, "mode", "off").lower()
            if not self.config.automation.enabled or mode == "off":
                if not self.config.automation.enabled:
                    continue
                # Dynamic migration for legacy code/tests toggling enabled=True with default mode
                mode = "prompt" if self.consent_provider else "auto"

            # 2. Rule approval and enabled check
            if not rule.approved or not rule.enabled:
                continue

            # 3. Schedule match
            if rule.day_of_week != current_dow or rule.time_bucket != current_time_bucket:
                continue

            # 4. Once-per-day trigger check (prevent rapid duplicate triggers in same bucket)
            if rule.last_triggered_date == local_date_str:
                continue

            # 5. Check if executable path is resolved
            if not rule.exe_path:
                log = AutomationLogRecord(
                    log_id=new_id("log"),
                    ts_utc=now_ts_str,
                    rule_id=rule.rule_id,
                    action="launch",
                    result="error",
                    reason=f"Executable path unresolved for {rule.app_name}",
                )
                self.store.append_automation_log(log)
                executed_logs.append(log)
                continue

            # 6. Duplicate running instance check
            if self.config.automation.prevent_duplicate_instances:
                if self.launcher.is_app_running(rule.app_name, rule.exe_path):
                    log = AutomationLogRecord(
                        log_id=new_id("log"),
                        ts_utc=now_ts_str,
                        rule_id=rule.rule_id,
                        action="launch",
                        result="skipped_duplicate",
                        reason=f"Application {rule.app_name} is already running",
                    )
                    self.store.append_automation_log(log)
                    executed_logs.append(log)
                    rule.last_triggered_date = local_date_str
                    continue

            # 7. Consent check according to automation mode
            if mode == "prompt":
                if not self.consent_provider:
                    # Item 12.3: Headless refusal to launch without consent channel
                    log = AutomationLogRecord(
                        log_id=new_id("log"),
                        ts_utc=now_ts_str,
                        rule_id=rule.rule_id,
                        action="prompt",
                        result="skipped_no_consent_channel",
                        reason="Prompt mode requires consent provider, but none is attached (headless mode)",
                    )
                    self.store.append_automation_log(log)
                    executed_logs.append(log)
                    rule.last_triggered_date = local_date_str
                    continue

                timeout_sec = self.config.automation.prompt_timeout_seconds
                response = self.consent_provider(rule, timeout_sec)
                if response == "reject":
                    log = AutomationLogRecord(
                        log_id=new_id("log"),
                        ts_utc=now_ts_str,
                        rule_id=rule.rule_id,
                        action="prompt",
                        result="rejected",
                        reason="User rejected launch prompt",
                    )
                    self.store.append_automation_log(log)
                    executed_logs.append(log)
                    rule.last_triggered_date = local_date_str
                    continue
                elif response == "timeout":
                    no_resp = self.config.automation.no_response_action.lower()
                    if no_resp == "skip":
                        log = AutomationLogRecord(
                            log_id=new_id("log"),
                            ts_utc=now_ts_str,
                            rule_id=rule.rule_id,
                            action="prompt",
                            result="timeout_skip",
                            reason=f"No response within {timeout_sec}s timeout; skipping launch",
                        )
                        self.store.append_automation_log(log)
                        executed_logs.append(log)
                        rule.last_triggered_date = local_date_str
                        continue
            elif mode == "notify":
                logger.info("Automation notify mode: rule %s (%s) executing", rule.rule_id, rule.app_name)

            # 8. Execute launch
            success, msg = self.launcher.launch(rule.exe_path)
            res_str = "success" if success else "error"
            log = AutomationLogRecord(
                log_id=new_id("log"),
                ts_utc=now_ts_str,
                rule_id=rule.rule_id,
                action="launch",
                result=res_str,
                reason=msg,
            )
            self.store.append_automation_log(log)
            executed_logs.append(log)
            rule.last_triggered_date = local_date_str

        return executed_logs
