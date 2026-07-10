import unittest

from worker.queue import drain_ready


class DrainReadyTests(unittest.TestCase):
    def test_preserves_input_order(self):
        self.assertEqual(drain_ready(["a", "b", "c"]), ["a", "b", "c"])

    def test_handles_single_item(self):
        self.assertEqual(drain_ready(["only"]), ["only"])


if __name__ == "__main__":
    unittest.main()
