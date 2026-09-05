from __future__ import annotations

import json
import unittest
from pathlib import Path


REGISTRATION_DIRECTORY = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "registrations"
    / "EXP-METHOD-PILOT-001"
)


class ExperimentRegistrationTests(unittest.TestCase):
    def test_archived_registration_preserves_the_legacy_schedule_metadata(self):
        registration = json.loads(
            (REGISTRATION_DIRECTORY / "registration.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(registration["status"], "archived")
        self.assertIsNone(registration["results"])
        self.assertEqual(
            sum(item["expected_episode_count"] for item in registration["subruns"]),
            registration["expected_episode_count"],
        )
        self.assertIn("not current CLI entry points", registration["archive_reason"])

    def test_temporal_sources_are_registered_without_an_evaluation_time(self):
        sources = json.loads(
            (REGISTRATION_DIRECTORY / "temporal_sources.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(sources["status"], "registered_before_evaluation")
        self.assertEqual(len(sources["records"]), 3)
        for record in sources["records"]:
            dates = [
                item["public_at"] for item in record["public_disclosures"]
            ]
            self.assertEqual(record["earliest_public_at"], min(dates))
            self.assertNotIn("evaluated_at", record)


if __name__ == "__main__":
    unittest.main()
