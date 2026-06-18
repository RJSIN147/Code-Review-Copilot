"""Unit tests for the diff parser utility."""

from app.utils.diff_parser import get_new_file_lines, is_line_in_diff, build_patch_index


SIMPLE_PATCH = (
    "@@ -1,4 +1,6 @@\n"
    " import os\n"  # context line  → new line 1
    "+import json\n"  # added line    → new line 2
    " \n"  # context line  → new line 3
    " def foo():\n"  # context line  → new line 4
    "-    pass\n"  # removed line  → NOT in new file
    "+    return 42\n"  # added line    → new line 5
    "+\n"  # added line    → new line 6
)

ADDED_FILE_PATCH = (
    "@@ -0,0 +1,3 @@\n"
    "+def hello():\n"  # new line 1
    "+    return 'hi'\n"  # new line 2
    "+\n"  # new line 3
)


class TestGetNewFileLines:
    def test_simple_patch_returns_correct_lines(self):
        result = get_new_file_lines(SIMPLE_PATCH)
        assert result == {1, 2, 3, 4, 5, 6}

    def test_removed_lines_are_excluded(self):
        result = get_new_file_lines(SIMPLE_PATCH)
        # Line that was "-    pass" should not appear
        # After removal, new file jumps from line 4 to lines 5 and 6
        # The old line 5 ("pass") is gone; new lines are numbered differently
        assert 1 in result  # "import os"
        assert 2 in result  # "+import json"

    def test_added_file_patch(self):
        result = get_new_file_lines(ADDED_FILE_PATCH)
        assert result == {1, 2, 3}

    def test_empty_patch_returns_empty_set(self):
        assert get_new_file_lines("") == set()
        assert get_new_file_lines(None) == set()

    def test_multiple_hunks(self):
        patch = (
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-old_line2\n"
            "+new_line2\n"
            " line3\n"
            "@@ -10,3 +10,4 @@\n"
            " line10\n"
            "+added_line\n"
            " line11\n"
            " line12\n"
        )
        result = get_new_file_lines(patch)
        assert 1 in result  # context line from first hunk
        assert 2 in result  # new_line2
        assert 3 in result  # line3
        assert 10 in result  # line10
        assert 11 in result  # added_line
        assert 12 in result  # line11
        assert 13 in result  # line12


class TestIsLineInDiff:
    def test_line_in_diff(self):
        assert is_line_in_diff(SIMPLE_PATCH, 1) is True
        assert is_line_in_diff(SIMPLE_PATCH, 2) is True

    def test_line_not_in_diff(self):
        # Line 100 is far outside the patched region
        assert is_line_in_diff(SIMPLE_PATCH, 100) is False

    def test_empty_patch_returns_false(self):
        assert is_line_in_diff("", 1) is False


class TestBuildPatchIndex:
    def test_builds_index_for_multiple_files(self):
        files = [
            {"filename": "app/main.py", "patch": SIMPLE_PATCH},
            {"filename": "app/new.py", "patch": ADDED_FILE_PATCH},
        ]
        index = build_patch_index(files)
        assert "app/main.py" in index
        assert "app/new.py" in index
        assert index["app/new.py"] == {1, 2, 3}

    def test_file_with_no_patch(self):
        files = [{"filename": "binary_file.png", "patch": ""}]
        index = build_patch_index(files)
        assert index["binary_file.png"] == set()

    def test_empty_list(self):
        assert build_patch_index([]) == {}
