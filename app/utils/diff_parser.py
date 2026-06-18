"""
Unified Diff Parser

Parses GitHub PR patch strings to determine which line numbers in the
new version of a file are visible in the diff. Only visible lines can
receive inline GitHub review comments.
"""

import re
from app.utils.logger import logger


def get_new_file_lines(patch: str) -> set[int]:
    """
    Parse a unified diff patch and return the set of line numbers in the
    **new** file that are visible in the diff (added lines and context lines).

    These are the only lines that can receive inline GitHub review comments
    when using the `line` + `side: "RIGHT"` parameter of the Reviews API.

    Args:
        patch: The unified diff string from GitHub's PR files API
               (the `patch` field on each file object).

    Returns:
        A set of integer line numbers (1-indexed) from the new file that
        appear in the diff. Returns an empty set if patch is empty or None.

    Example:
        patch = "@@ -1,4 +1,6 @@\\n import os\\n+import json\\n def foo():\\n-    pass\\n+    return 42\\n"
        get_new_file_lines(patch)  # → {1, 2, 3, 5}
        # Line 4 (old "pass") is gone; line 5 is the new "    return 42"
    """
    if not patch:
        return set()

    visible: set[int] = set()
    current_new_line: int = 0

    for raw_line in patch.split("\n"):
        if not raw_line and raw_line != " ":
            # Skip empty strings from trailing newlines in split
            continue
        if raw_line.startswith("@@"):
            # Header: @@ -old_start[,old_count] +new_start[,new_count] @@
            match = re.search(r"\+(\d+)(?:,(\d+))?", raw_line)
            if match:
                # new_start is 1-indexed; subtract 1 because we increment before use
                current_new_line = int(match.group(1)) - 1
        elif raw_line.startswith("+"):
            # Added line — exists in the new file
            current_new_line += 1
            visible.add(current_new_line)
        elif raw_line.startswith("-"):
            # Removed line — exists only in the old file; do not advance new counter
            continue
        elif raw_line.startswith("\\"):
            # "\ No newline at end of file" — metadata, skip
            continue
        else:
            # Context line (starts with a space, or empty in some edge cases)
            # Exists in both old and new file
            current_new_line += 1
            visible.add(current_new_line)

    logger.debug(f"Diff parser found {len(visible)} visible lines in patch")
    return visible


def is_line_in_diff(patch: str, line_number: int) -> bool:
    """
    Return True if `line_number` (1-indexed, new file) is visible in the diff.

    Args:
        patch: Unified diff patch string from GitHub API.
        line_number: 1-indexed line number in the new version of the file.

    Returns:
        True if the line can receive an inline comment, False otherwise.
    """
    return line_number in get_new_file_lines(patch)


def build_patch_index(files_data: list[dict]) -> dict[str, set[int]]:
    """
    Build a filename → visible-line-numbers index from a list of file dicts.

    Args:
        files_data: List of file dicts, each expected to have "filename" and
                    "patch" keys (as returned by GitHubService.get_pull_request_files
                    and stored in files_for_analysis after Step 2).

    Returns:
        Dict mapping filename → set of visible line numbers.
    """
    index: dict[str, set[int]] = {}
    for f in files_data:
        filename = f.get("filename", "")
        patch = f.get("patch", "")
        index[filename] = get_new_file_lines(patch)
    logger.debug(f"Built patch index for {len(index)} files")
    return index
