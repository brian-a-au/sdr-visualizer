"""CLI exit codes (SPEC §7).

The visualizer has no equivalent of the grader's "below threshold" failure
mode, so there is no exit code 2.
"""

SUCCESS = 0
RUNTIME_ERROR = 1
INPUT_VALIDATION_ERROR = 3
