"""Analytics package for Desktop Intelligence."""

from desktop_intelligence.analytics.clean import clean_sessions_df, clean_samples_df, clean_events_df
from desktop_intelligence.analytics.usage import calculate_usage_summary, calculate_daily_summary, calculate_app_baselines
from desktop_intelligence.analytics.resources import analyze_resource_hogs
from desktop_intelligence.analytics.patterns import detect_launch_patterns
from desktop_intelligence.analytics.recommendations import generate_recommendations

__all__ = [
    "clean_sessions_df",
    "clean_samples_df",
    "clean_events_df",
    "calculate_usage_summary",
    "calculate_daily_summary",
    "calculate_app_baselines",
    "analyze_resource_hogs",
    "detect_launch_patterns",
    "generate_recommendations",
]
