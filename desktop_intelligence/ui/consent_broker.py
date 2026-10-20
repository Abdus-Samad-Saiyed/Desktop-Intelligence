"""Thread-safe launch consent broker bridging background threads to Qt main GUI thread."""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QWidget

from desktop_intelligence.automation.rules import AutomationRule
from desktop_intelligence.ui.dialogs.consent_prompt import show_launch_consent_dialog

logger = logging.getLogger(__name__)


class ConsentBroker(QObject):
    """Bridges automation background worker thread requests to the Qt main thread."""

    request_consent_signal = Signal(object, int, object)

    def __init__(self, parent_window: Optional[QWidget] = None):
        super().__init__()
        self.parent_window = parent_window
        self.request_consent_signal.connect(self._on_request_consent)

    def request_consent(self, rule: AutomationRule, timeout_seconds: int = 10) -> str:
        """Request user consent for an automation rule launch.

        Thread-safe: can be called from background worker threads or the Qt GUI thread.
        Returns 'approve', 'reject', or 'timeout'.
        """
        # If already running on GUI thread, show dialog directly
        if QThread.currentThread() == self.thread():
            return show_launch_consent_dialog(rule, timeout_seconds, parent=self.parent_window)

        future: concurrent.futures.Future[str] = concurrent.futures.Future()
        self.request_consent_signal.emit(rule, timeout_seconds, future)
        try:
            # Wait for user input or dialog timeout (with generous margin over dialog timer)
            return future.result(timeout=timeout_seconds + 5)
        except concurrent.futures.TimeoutError:
            logger.warning("Consent dialog timed out waiting for future response for rule %s", rule.rule_id)
            return "timeout"
        except Exception as exc:
            logger.error("Error during consent broker dispatch for rule %s: %s", rule.rule_id, exc)
            return "reject"

    @Slot(object, int, object)
    def _on_request_consent(self, rule: AutomationRule, timeout_seconds: int, future: concurrent.futures.Future) -> None:
        """Slot executed strictly on the Qt main GUI thread."""
        try:
            choice = show_launch_consent_dialog(rule, timeout_seconds, parent=self.parent_window)
            future.set_result(choice)
        except Exception as exc:
            future.set_exception(exc)
