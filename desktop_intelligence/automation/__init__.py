"""Automation package for Desktop Intelligence."""

from desktop_intelligence.automation.rules import AutomationRule, sync_rules_from_recommendations
from desktop_intelligence.automation.launcher import BaseLauncher, SafeProcessLauncher, FakeLauncher
from desktop_intelligence.automation.scheduler import AutomationScheduler

__all__ = [
    "AutomationRule",
    "sync_rules_from_recommendations",
    "BaseLauncher",
    "SafeProcessLauncher",
    "FakeLauncher",
    "AutomationScheduler",
]
