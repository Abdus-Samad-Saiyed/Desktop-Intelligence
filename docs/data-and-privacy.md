# Data collection and privacy

Desktop Intelligence is designed to process monitoring records locally. Its data can still be sensitive because it describes how a person uses a computer. Review these behaviors before running it, especially on a shared or managed device.

## What the application can collect

Collection depends on `config.toml`, Windows capabilities, and which collectors are enabled.

| Source | Information recorded |
| --- | --- |
| Foreground-window events | Time of a foreground change, process name, process ID, and event metadata used to filter transient shell windows |
| Process-start events | Process name, process ID, start time, and available process metadata |
| Resource snapshots | Process memory (RSS), process memory percentage, cumulative CPU time, system memory pressure, and the event that triggered a sample |
| Session analytics | Application/process name, active and idle durations, local date, weekday, and time bucket |
| Application inventory | Installed application display name, executable path where available, discovery source, first/last observation, and observed launch counts |
| Windows reliability events | Selected Application log crash/hang information, including application, event time, code/module fields, and diagnostic description |
| Recommendations and automation | Recommendation evidence and status; scheduled action, outcome, and reason in the automation audit log |

Window titles are disabled by default (`collection.collect_window_titles = false`). Even without titles, process names, timestamps, executable paths, usage durations, and error descriptions can identify a person's work patterns. Windows event descriptions are system-provided text and may contain additional details.

## Where records go

By default, configuration, data, and logs are under `%LOCALAPPDATA%\DesktopIntelligence` on Windows:

```text
%LOCALAPPDATA%\DesktopIntelligence\
  config.toml
  data\
    activity_events.csv
    activity_sessions.csv
    resource_samples.csv
    application_inventory.csv
    recommendations.csv
    automation_log.csv
  logs\
```

The `[paths]` settings in the active configuration can change the data and log directories. These files are not encrypted by the application. Protect them using the account and disk security controls on the computer. Do not attach them to bug reports or publish them in a repository without reviewing their contents.

## Network and external services

The monitoring and analytics code writes to local files and does not require a project account or remote analytics service. Dependency installation needs network access to the configured Python package index. The configuration includes an LLM section, but it is disabled by default, selects no provider, and sets raw-event sharing to false; this repository does not currently implement an external LLM integration.

## Automation

Scheduled application launching is optional and disabled by default. The UI offers explicit automation modes; rules can require approval, prompts time out to the configured safe action (skip by default), and attempts are recorded. Review approved rules and the automation log. Headless collector mode has no interactive consent channel and skips consent-dependent launches.

## Retention and removal

Retention periods are configurable under `[retention]` for event, session, and resource records. Review the active settings and stored files when deciding how long to keep data. To remove collected history, close the application and delete the CSV files in the configured data directory. Removing the application source does not delete data kept in the per-user data directory.

## Demo data

`--demo-mode` creates deterministic synthetic records in a temporary directory, separate from the normal user data directory. The checked-in screenshots also use illustrative sample data and are not real user records.

## Before sharing a report

Review the files for process names, IDs, timestamps, installed software, executable paths, resource samples, Windows diagnostic text, and automation actions. Prefer a reproducible description or synthetic demo output over raw monitoring files.
