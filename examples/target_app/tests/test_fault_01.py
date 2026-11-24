import unittest
from src.fault_01 import calculate_total

class RegressionTest(unittest.TestCase):
    def test_reproduces_and_prevents_fault_01_regression(self):
        self.assertEqual(calculate_total([10, 20, 30]), 60)

if __name__ == "__main__":
    unittest.main()
