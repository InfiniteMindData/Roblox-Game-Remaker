#!/usr/bin/env python3
"""Deprecated compatibility alias for wording_lint.py, NOT an outcome grader."""
import sys
from wording_lint import main

if __name__ == "__main__":
    print("warning: grade.py is wording lint only; use grade_outcomes.py for artifacts", file=sys.stderr)
    sys.exit(main())
