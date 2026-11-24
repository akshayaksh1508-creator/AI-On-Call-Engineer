import unittest
from src.fault_05 import is_success

class RegressionTest(unittest.TestCase):
    def test_reproduces_and_prevents_fault_05_regression(self):
        self.assertEqual(is_success(302), True)

if __name__ == "__main__":
    unittest.main()
