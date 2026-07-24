"""Copy this contract into a trusted internal module; do not put company rules here."""

from pathlib import Path


def analyze_log_bundle(*, files: dict[str, str], archive_path: Path) -> dict:
    """Return normalized, deterministic findings for one already-read BMC archive.

    `files` maps archive paths to UTF-8 text.  Do not execute data from the
    archive and do not transmit raw contents outside the approved environment.
    """
    # Replace the empty list with verified company rules.  The payload below is
    # deliberately inert so configuring the example never creates fake alarms.
    return {
        "skill_name": "company-bmc-parser",
        "skill_version": "replace-with-internal-version",
        "findings": [],
    }
