import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import history  # noqa: E402

TODAY = date(2026, 10, 8)


class HistoryTest(unittest.TestCase):
    def test_record_merges_and_keeps_all_by_default(self):
        h = {"2020-01-01": {"a/b": 1}, "2026-10-07": {"a/b": 10}}
        history.record(h, TODAY, {"a/b": 12, "c/d": 5})
        history.record(h, TODAY, {"a/b": 99, "e/f": 7})  # 同じ日は最初の値を残し、無いものだけ足す
        self.assertIn("2020-01-01", h)  # 既定は無制限
        self.assertEqual(h["2026-10-08"], {"a/b": 12, "c/d": 5, "e/f": 7})

    def test_record_prunes_when_keep_days_given(self):
        h = {"2026-08-01": {"a/b": 1}, "2026-10-07": {"a/b": 10}}
        history.record(h, TODAY, {"a/b": 12}, keep_days=35)
        self.assertEqual(sorted(h), ["2026-10-07", "2026-10-08"])

    def test_base_date(self):
        h = {"2026-09-29": {}, "2026-10-01": {}, "2026-10-02": {}, "2026-10-08": {}}
        self.assertEqual(history.base_date(h, TODAY, 7), "2026-10-01")  # 7 日前ちょうど
        self.assertEqual(history.base_date(h, TODAY, 6), "2026-10-02")
        self.assertEqual(history.base_date(h, TODAY, 30), "2026-09-29")  # 足りなければ最も古い記録
        self.assertIsNone(history.base_date({"2026-10-08": {}}, TODAY, 7))  # 今日の分だけ
        self.assertIsNone(history.base_date({}, TODAY, 7))

    def test_base_date_per_category(self):
        h = {"2026-09-30": {"f/a": 1, "b/a": 1}, "2026-10-01": {"f/a": 2}}  # 10/01 は backend が欠けた
        self.assertEqual(history.base_date(h, TODAY, 7, ["f/a"]), "2026-10-01")
        self.assertEqual(history.base_date(h, TODAY, 7, ["b/a"]), "2026-09-30")
        self.assertIsNone(history.base_date(h, TODAY, 7, ["x/y"]))

    def test_load_rejects_broken_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "stars.json"
            for text in ("<<<<<<< HEAD\n{}", "[]", '{"2026-10-08": 1}'):
                path.write_text(text)
                with self.assertRaises(SystemExit):
                    history.load(path)

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / ".state" / "stars.json"
            self.assertEqual(history.load(path), {})
            h = {"2026-10-08": {"z/z": 2, "a/a": 1}, "2026-10-07": {"a/a": 0}}
            history.save(h, path)
            self.assertEqual(history.load(path), h)
            lines = path.read_text().splitlines()
            self.assertTrue(lines[1].startswith('  "2026-10-07"'))  # 日付順・1 日 1 行
            self.assertIn('{"a/a": 1, "z/z": 2}', lines[2])


if __name__ == "__main__":
    unittest.main()
