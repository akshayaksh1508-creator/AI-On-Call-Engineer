"""Fix generation and regression validation package. Owner: Person B."""

from fixer.fixer import Fixer, FixValidationError, select_fix_type
from fixer.regression import (
    RegressionResult,
    RegressionTestError,
    verify_fail_then_pass,
    write_regression_test,
)

__all__ = [
    "Fixer",
    "FixValidationError",
    "RegressionResult",
    "RegressionTestError",
    "select_fix_type",
    "verify_fail_then_pass",
    "write_regression_test",
]
