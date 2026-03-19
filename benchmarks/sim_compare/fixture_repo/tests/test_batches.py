import unittest

from worker.batches import collect_batches


class CollectBatchesTests(unittest.TestCase):
    def test_collects_full_batches(self):
        result = collect_batches(["a", "b", "c", "d"], 2)

        self.assertEqual(result, [["a", "b"], ["c", "d"]])

    def test_keeps_trailing_partial_batch(self):
        result = collect_batches(["a", "b", "c"], 2)

        self.assertEqual(result, [["a", "b"], ["c"]])


if __name__ == "__main__":
    unittest.main()
