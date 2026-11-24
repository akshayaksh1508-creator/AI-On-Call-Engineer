import unittest
from src.fault_03 import retry_delay

class RegressionTest(unittest.TestCase):
    def test_reproduces_and_prevents_fault_03_regression(self):
        self.assertEqual(retry_delay(3), 8)

if __name__ == "__main__":
    unittest.main()
