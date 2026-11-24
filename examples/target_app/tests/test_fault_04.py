import unittest
from src.fault_04 import parse_quantity

class RegressionTest(unittest.TestCase):
    def test_reproduces_and_prevents_fault_04_regression(self):
        self.assertEqual(parse_quantity({}), 0)

if __name__ == "__main__":
    unittest.main()
