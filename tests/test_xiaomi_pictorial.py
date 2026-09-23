import unittest

from xiaomi_pictorial import (
    MorningRecord,
    extract_morning_records,
    make_base_name,
    reorder_candidates,
)


class ExtractMorningRecordsTest(unittest.TestCase):
    def test_extracts_multiple_quality_candidates(self):
        payload = {
            "items": [
                {
                    "id": "abc123",
                    "exparam": {"morning_date": "2026-09-23"},
                    "meta": {"title": "早安 世界", "desc": "今天也要加油"},
                    "images": [{
                        "cl_url": {
                            "url_full": "http://example.com/full.jpg",
                            "url_h": "http://example.com/high.jpg",
                            "url_root": "http://cdn.example.com/",
                            "locator": "foo/bar",
                        }
                    }],
                }
            ]
        }

        record = extract_morning_records(payload)[0]
        self.assertEqual("https://example.com/full.jpg", record.image_url)
        self.assertIn(
            "https://cdn.example.com/webp/w2160/foo/bar",
            record.image_candidates,
        )
        self.assertIn(
            "https://cdn.example.com/webp/w1080/foo/bar",
            record.image_candidates,
        )

    def test_quality_ordering_prefers_requested_generated_width(self):
        urls = [
            "https://example.com/full.jpg",
            "https://cdn.example.com/webp/w1080/a",
            "https://cdn.example.com/webp/w2160/a",
            "https://cdn.example.com/webp/w1440/a",
        ]
        ordered = reorder_candidates(urls, "2160")
        self.assertEqual("https://example.com/full.jpg", ordered[0])
        self.assertEqual("https://cdn.example.com/webp/w2160/a", ordered[1])

    def test_filename_modes(self):
        record = MorningRecord(
            morning_date="2026-09-23",
            item_id="1",
            title="早安 世界",
            description="",
            image_url="",
            image_candidates=[],
            raw={},
        )
        self.assertEqual("2026-09-23", make_base_name(record, "date"))
        self.assertEqual("早安 世界", make_base_name(record, "title"))
        self.assertEqual(
            "2026-09-23 早安 世界",
            make_base_name(record, "date_title"),
        )


if __name__ == "__main__":
    unittest.main()
