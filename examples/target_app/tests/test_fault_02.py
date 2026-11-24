import unittest
from src.fault_02 import normalize_status

class RegressionTest(unittest.TestCase):
    def test_reproduces_and_prevents_fault_02_regression(self):
        self.assertEqual(normalize_status(' PAID '), 'complete')

if __name__ == "__main__":
    unittest.main()
