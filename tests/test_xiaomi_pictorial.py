import unittest

from xiaomi_pictorial import extract_morning_records, sanitize_filename


class ExtractMorningRecordsTest(unittest.TestCase):
    def test_extracts_date_text_and_hd_image(self):
        payload = {
            "items": [
                {
                    "id": "abc123",
                    "exparam": {"morning_date": "2026-09-23"},
                    "meta": {"title": "早安", "desc": "今天也要加油"},
                    "images": [
                        {
                            "cl_url": {
                                "url_h": "http://example.com/original.jpg",
                                "url_root": "http://cdn.example.com/",
                                "locator": "foo/bar",
                            }
                        }
                    ],
                }
            ]
        }

        records = extract_morning_records(payload)
        self.assertEqual(1, len(records))
        record = records[0]
        self.assertEqual("2026-09-23", record.morning_date)
        self.assertEqual("早安", record.title)
        self.assertEqual("今天也要加油", record.description)
        self.assertEqual("https://example.com/original.jpg", record.image_url)

    def test_falls_back_to_cdn_locator(self):
        payload = {
            "data": {
                "list": [
                    {
                        "id": "x",
                        "exparam": '{"morning_date":"2025-01-02"}',
                        "images": [
                            {
                                "cl_url": {
                                    "url_root": "http://cdn.example.com/",
                                    "locator": "/folder/image",
                                }
                            }
                        ],
                    }
                ]
            }
        }

        record = extract_morning_records(payload, width=2160)[0]
        self.assertEqual(
            "https://cdn.example.com/webp/w2160/folder/image",
            record.image_url,
        )

    def test_sanitize_filename(self):
        self.assertEqual("a_b_c", sanitize_filename('a<b>c'))


if __name__ == "__main__":
    unittest.main()
