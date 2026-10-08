import unittest

from scripts.import_priority_network_price_archive import RECORDS, validate_record


class NetworkPriceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.record = dict(next(r for r in RECORDS if r.get("source") == "redapteka_archive"))
        self.med = {
            "name": "Этамбутол",
            "manufacturer": "ФАРМСИНТЕЗ",
            "variants": [{"pack_size": "100 шт"}],
        }

    def test_explicitly_approved_reference_is_allowed(self):
        validate_record(self.med, self.record)

    def test_manufacturer_difference_is_not_silently_equated(self):
        self.record.pop("reference_approved_at")
        with self.assertRaisesRegex(ValueError, "manufacturer mismatch"):
            validate_record(self.med, self.record)

    def test_approval_is_bound_to_target(self):
        self.med["manufacturer"] = "Другая компания"
        with self.assertRaisesRegex(ValueError, "manufacturer mismatch"):
            validate_record(self.med, self.record)

    def test_wrong_pack_is_rejected(self):
        self.record["gz_pack"] = "50 шт"
        with self.assertRaisesRegex(ValueError, "pack mismatch"):
            validate_record(self.med, self.record)

    def test_other_hosts_and_mislabelled_sources_are_rejected(self):
        for url in ("https://redapteka.ru.evil.test/catalog/test", "https://redapteka.ru@evil.test/catalog/test"):
            with self.subTest(url=url):
                self.record["source_url"] = url
                with self.assertRaisesRegex(ValueError, "non-network source"):
                    validate_record(self.med, self.record)
        self.record["source_url"] = "https://redapteka.ru/catalog/test"
        self.record["source"] = "rigla_archive"
        with self.assertRaisesRegex(ValueError, "non-network source"):
            validate_record(self.med, self.record)


if __name__ == "__main__":
    unittest.main()
