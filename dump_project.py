"""Project dump utility — exports project source for review.

Excludes sensitive files (.env, debug_accounts.md, etc.), binary files,
virtual environments, and generated artifacts.
"""

import os

OUTPUT_FILE = "project_dump.txt"

EXCLUDED_DIRS = {
    "myenv",
    ".myenv",
    "venv",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".idea",
    ".vscode",
    "node_modules",
    "migrations",
    "staticfiles",
    "media",
}

EXCLUDED_EXTENSIONS = {
    ".pyc",
    ".sqlite3",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".rar",
    ".7z",
    ".exe",
    ".dll",
    ".log",
    ".env",
}

# Files that must never be included (secrets, credentials, local data).
EXCLUDED_FILES = {
    ".env",
    "debug_accounts.md",
    "superuser_password",
    "project_dump.txt",
    "db.sqlite3",
}

ROOT_DIR = "."


def should_skip_file(filename):
    """Return True if the file should be excluded from the dump."""
    # Exact filename match
    if filename.lower() in {f.lower() for f in EXCLUDED_FILES}:
        return True

    # Extension match
    _, ext = os.path.splitext(filename)
    if ext.lower() in EXCLUDED_EXTENSIONS:
        return True

    return False


with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8"
) as output:

    for root, dirs, files in os.walk(ROOT_DIR):

        dirs[:] = [
            d for d in dirs
            if d not in EXCLUDED_DIRS
        ]

        for file in files:

            if should_skip_file(file):
                continue

            filepath = os.path.join(root, file)

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                content = f"[ERROR READING FILE: {e}]"

            separator = "=" * 80

            output.write(f"\n{separator}\n")
            output.write(f"FILE: {filepath}\n")
            output.write(f"{separator}\n\n")
            output.write(content)
            output.write("\n\n")

print(f"Project dump written to {OUTPUT_FILE}")