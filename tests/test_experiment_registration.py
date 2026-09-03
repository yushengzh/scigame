from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from experiments.run_case_matrix import _parser, run_matrix


REGISTRATION_DIRECTORY = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "registrations"
    / "EXP-METHOD-PILOT-001"
)


class ExperimentRegistrationTests(unittest.TestCase):
    def test_registered_subruns_generate_the_frozen_schedule(self):
        registration = json.loads(
            (REGISTRATION_DIRECTORY / "registration.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(registration["status"], "ready")
        self.assertIsNone(registration["results"])

        observed_total = 0
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for subrun in registration["subruns"]:
                with self.subTest(subrun=subrun["subrun_id"]):
                    argv = list(subrun["command"][2:])
                    output_index = argv.index("--output-dir") + 1
                    argv[output_index] = str(root / subrun["subrun_id"])
                    argv.append("--dry-run")
                    args = _parser().parse_args(argv)
                    with contextlib.redirect_stdout(io.StringIO()):
                        run_matrix(args)
                    config = json.loads(
                        (Path(args.output_dir) / "config.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    expected = subrun["expected_episode_count"]
                    self.assertEqual(config["experiment_id"], registration["experiment_id"])
                    self.assertEqual(config["schedule"]["seed"], registration["schedule_seed"])
                    self.assertEqual(config["design"]["total_episodes"], expected)
                    self.assertEqual(config["oracle_generation"]["mode"], "deterministic")
                    observed_total += expected

        self.assertEqual(observed_total, registration["expected_episode_count"])

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
