import os
import unittest

from tests import helpers  # noqa: F401  (puts roundup/lib on sys.path)
from roundup import timefmt


class TimefmtTest(unittest.TestCase):
    def test_us_to_iso(self):
        self.assertEqual(timefmt.us_to_iso(1795320000000000), "2026-11-22T04:00:00Z")
        self.assertIsNone(timefmt.us_to_iso(0))
        self.assertIsNone(timefmt.us_to_iso(None))

    def test_ms_to_iso(self):
        self.assertEqual(timefmt.ms_to_iso(1795320000123), "2026-11-22T04:00:00Z")
        self.assertIsNone(timefmt.ms_to_iso(None))

    def test_parse_iso(self):
        dt = timefmt.parse_iso("2026-11-22T09:15:00Z")
        self.assertEqual((dt.hour, dt.minute), (9, 15))
        self.assertIsNotNone(timefmt.parse_iso("2026-10-30T06:37:54.76Z"))
        self.assertIsNotNone(timefmt.parse_iso("2026-10-30T06:37:54+02:00"))
        self.assertIsNone(timefmt.parse_iso(None))

    def test_parse_duration(self):
        self.assertEqual(timefmt.parse_duration("3d"), 3 * 86400)
        self.assertEqual(timefmt.parse_duration("12h"), 12 * 3600)
        self.assertEqual(timefmt.parse_duration("30m"), 1800)
        for bad in ("3", "d", "3w", "-1d", "0d", "1.5d", "", "3 d"):
            with self.assertRaises(ValueError):
                timefmt.parse_duration(bad)

    def test_format_duration(self):
        self.assertEqual(timefmt.format_duration(5 * 86400 + 3 * 3600 + 59), "5d 3h")
        self.assertEqual(timefmt.format_duration(2 * 3600 + 10 * 60), "2h 10m")
        self.assertEqual(timefmt.format_duration(4 * 60 + 5), "4m")
        self.assertEqual(timefmt.format_duration(0), "0m")
        self.assertEqual(timefmt.format_duration(86400), "1d")

    def test_seconds_between_and_now_override(self):
        self.assertEqual(
            timefmt.seconds_between("2026-11-22T10:00:00Z", "2026-11-22T12:00:00Z"), 7200
        )
        self.assertIsNone(timefmt.seconds_between(None, "2026-11-22T12:00:00Z"))
        saved = os.environ.get("ROUNDUP_NOW")
        os.environ["ROUNDUP_NOW"] = "2026-11-22T12:00:00Z"
        try:
            self.assertEqual(timefmt.now_iso(), "2026-11-22T12:00:00Z")
        finally:
            if saved is None:
                os.environ.pop("ROUNDUP_NOW")
            else:
                os.environ["ROUNDUP_NOW"] = saved


if __name__ == "__main__":
    unittest.main()
