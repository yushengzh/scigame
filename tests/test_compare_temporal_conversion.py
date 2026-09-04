from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from experiments.compare_temporal_conversion import compare_temporal_conversion


def _write(path: Path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _rate(count):
    return {"count": count, "denominator": 37, "rate": count / 37}


class TemporalConversionComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        sources = [
            {
                "order": index,
                "paper_id": "paper_%02d" % index,
                "max_total_attempts": 2,
            }
            for index in range(1, 38)
        ]
        _write(
            self.root / "frozen_sources.json",
            {"cohort_size": 37, "sources": sources},
        )
        self.registration = {
            "experiment_id": "EXP-TEMPORAL-AUTHORING-001",
            "status": "blocked_pending_snapshot_and_credentials",
            "cohort_size": 37,
            "source_manifest": "frozen_sources.json",
            "authoring_model": {
                "provider": "provider",
                "api": "chat_completions",
                "endpoint": "https://provider.invalid/v1/chat/completions",
                "model_id": "mutable-model-alias",
                "checkpoint_or_snapshot_id": "unknown",
                "knowledge_cutoff": {
                    "status": "unknown",
                    "date": None,
                    "evidence_locator": None,
                },
                "thinking": "disabled",
                "temperature": 0.0,
                "top_p": 1.0,
                "max_output_tokens": 4096,
                "reasoning_effort": None,
                "timeout_s": 180.0,
            },
            "call_budget": {"maximum_attempts_total": 74},
            "historical_baseline": {
                "comparison_status": "descriptive_only",
                "authoring_model_checkpoint_or_snapshot_id": "unknown",
                "metrics": {
                    "first_attempt_structural_validity_rate": {
                        "numerator": 3,
                        "denominator": 37,
                        "rate": 3 / 37,
                    },
                    "post_repair_structural_validity_rate": {
                        "numerator": 13,
                        "denominator": 37,
                        "rate": 13 / 37,
                    },
                    "source_review_retention_rate": {
                        "numerator": 0,
                        "denominator": 37,
                        "rate": 0.0,
                        "card_revision_required_count": 6,
                    },
                    "final_acceptance_rate": {
                        "numerator": 0,
                        "denominator": 37,
                        "rate": 0.0,
                    },
                },
            },
        }
        self.paper_results = []
        for index in range(1, 38):
            common = {
                "paper_id": "paper_%02d" % index,
                "attempt_count": 1 if index <= 10 else 2,
                "structural_valid": index <= 20,
                "first_attempt_structural_valid": index <= 10,
                "nonempty_relation": index <= 20,
                "source_review_completed": index <= 20,
            }
            if index <= 20:
                common["completed_response_count"] = 1 if index <= 10 else 2
            if index <= 5:
                status = "case_accepted"
            elif index <= 8:
                status = "construction_rejected"
            elif index <= 14:
                status = "card_revision_required"
            elif index <= 20:
                status = "source_review_rejected"
            else:
                status = "science_card_generation_failed"
            self.paper_results.append({**common, "status": status})
        self.metrics = {
            "cohort_size": 37,
            "actual_science_card_calls": 64,
            "first_attempt_structural_validity": _rate(10),
            "post_repair_structural_validity": _rate(20),
            "nonempty_relation": _rate(20),
            "source_review": {
                "complete": True,
                "completed_count": 20,
                "eligible_count": 8,
                "card_revision_required_count": 6,
                "rejected_count": 6,
                "conditional_retention_rate": 8 / 20,
                "unconditional_retention_rate": 8 / 37,
            },
            "final_acceptance": _rate(5),
            "historical_snapshot_comparable": False,
        }
        self.config = {
            "schema": "role_benchmark.temporal_conversion_run.v1",
            "experiment_id": "EXP-TEMPORAL-AUTHORING-001",
            "registration": str((self.root / "registration.json").resolve()),
            "source_manifest": "frozen_sources.json",
            "cohort_size": 37,
            "process_all_sources": True,
            "model": {
                "provider": "provider",
                "api": "chat_completions",
                "endpoint": "https://provider.invalid/v1/chat/completions",
                "model_id": "mutable-model-alias",
                "checkpoint_or_snapshot_id": "unknown",
                "provider_request_model": "unknown",
                "knowledge_cutoff": {
                    "status": "unknown",
                    "date": None,
                    "evidence_locator": None,
                },
                "thinking": "disabled",
                "reasoning_effort": None,
            },
            "generation": {
                "temperature": 0.0,
                "top_p": 1.0,
                "max_output_tokens": 4096,
                "per_source_max_total_attempts": "frozen_sources.json",
            },
            "historical_snapshot_comparable": False,
            "dry_run": False,
        }

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _compare(
        self,
        *,
        registration=None,
        config=None,
        metrics=None,
        paper_results=None,
    ):
        registration_path = self.root / "registration.json"
        result_path = self.root / "result.json"
        metrics_path = self.root / "metrics.json"
        registration = registration or self.registration
        config = config or self.config
        metrics = metrics or self.metrics
        paper_results = paper_results or self.paper_results
        _write(registration_path, registration)
        _write(self.root / "config.json", config)
        _write(metrics_path, metrics)
        _write(
            result_path,
            {
                "experiment_id": "EXP-TEMPORAL-AUTHORING-001",
                "status": "complete",
                "metrics": metrics,
                "paper_results": paper_results,
            },
        )
        return compare_temporal_conversion(registration_path, result_path, metrics_path)

    def test_reports_four_descriptive_differences(self):
        comparison = self._compare()
        self.assertEqual(comparison["comparison_status"], "descriptive_only")
        self.assertEqual(len(comparison["metrics"]), 4)
        source_review = comparison["metrics"]["source_review_retention_rate"]
        self.assertEqual(source_review["historical"]["numerator"], 0)
        self.assertEqual(source_review["revised"]["numerator"], 8)
        self.assertAlmostEqual(source_review["percentage_point_difference"], 800 / 37)
        lower, upper = source_review[
            "revised_exact_binomial_confidence_interval_95"
        ]
        self.assertLess(lower, 8 / 37)
        self.assertGreater(upper, 8 / 37)
        self.assertIn("No causal effect", comparison["interpretation"])

    def test_reports_controlled_comparison_for_exact_preregistered_snapshot(self):
        registration = copy.deepcopy(self.registration)
        registration["status"] = "ready_for_execution"
        registration["authoring_model"]["checkpoint_or_snapshot_id"] = "snapshot-123"
        registration["historical_baseline"].update(
            {
                "comparison_status": "controlled",
                "authoring_model_checkpoint_or_snapshot_id": "snapshot-123",
            }
        )
        config = copy.deepcopy(self.config)
        config["model"]["checkpoint_or_snapshot_id"] = "snapshot-123"
        config["model"]["provider_request_model"] = "snapshot-123"
        config["historical_snapshot_comparable"] = True
        metrics = copy.deepcopy(self.metrics)
        metrics["historical_snapshot_comparable"] = True
        comparison = self._compare(
            registration=registration,
            config=config,
            metrics=metrics,
        )
        self.assertEqual(comparison["comparison_status"], "controlled")
        self.assertIn("controlled comparison", comparison["interpretation"])
        self.assertIn("No statistical significance claim", comparison["interpretation"])

    def test_mutable_alias_does_not_establish_controlled_comparison(self):
        comparison = self._compare()
        self.assertEqual(comparison["comparison_status"], "descriptive_only")

    def test_rejects_controlled_registration_with_different_historical_snapshot(self):
        registration = copy.deepcopy(self.registration)
        registration["status"] = "ready_for_execution"
        registration["authoring_model"]["checkpoint_or_snapshot_id"] = "snapshot-123"
        registration["historical_baseline"].update(
            {
                "comparison_status": "controlled",
                "authoring_model_checkpoint_or_snapshot_id": "snapshot-122",
            }
        )
        config = copy.deepcopy(self.config)
        config["model"]["checkpoint_or_snapshot_id"] = "snapshot-123"
        config["model"]["provider_request_model"] = "snapshot-123"
        config["historical_snapshot_comparable"] = True
        with self.assertRaisesRegex(ValueError, "identical historical"):
            self._compare(registration=registration, config=config)

    def test_rejects_alias_as_provider_request_model_for_controlled_run(self):
        registration = copy.deepcopy(self.registration)
        registration["status"] = "ready_for_execution"
        registration["authoring_model"]["checkpoint_or_snapshot_id"] = "snapshot-123"
        registration["historical_baseline"].update(
            {
                "comparison_status": "controlled",
                "authoring_model_checkpoint_or_snapshot_id": "snapshot-123",
            }
        )
        config = copy.deepcopy(self.config)
        config["model"]["checkpoint_or_snapshot_id"] = "snapshot-123"
        config["model"]["provider_request_model"] = "mutable-model-alias"
        with self.assertRaisesRegex(ValueError, "provider_request_model"):
            self._compare(registration=registration, config=config)

    def test_rejects_revision_required_as_historical_retention(self):
        registration = copy.deepcopy(self.registration)
        metric = registration["historical_baseline"]["metrics"][
            "source_review_retention_rate"
        ]
        metric.update({"numerator": 6, "rate": 6 / 37})
        with self.assertRaisesRegex(ValueError, "expected 0/37"):
            self._compare(registration=registration)

    def test_rejects_incomplete_source_review(self):
        metrics = copy.deepcopy(self.metrics)
        metrics["source_review"]["complete"] = False
        papers = copy.deepcopy(self.paper_results)
        papers[19]["source_review_completed"] = False
        papers[19]["status"] = "awaiting_source_review"
        metrics["source_review"].update(
            {
                "completed_count": 19,
                "rejected_count": 5,
                "conditional_retention_rate": None,
                "unconditional_retention_rate": None,
            }
        )
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self._compare(metrics=metrics, paper_results=papers)

    def test_rejects_empty_relation_counted_as_structurally_valid(self):
        metrics = copy.deepcopy(self.metrics)
        papers = copy.deepcopy(self.paper_results)
        papers[19]["nonempty_relation"] = False
        with self.assertRaisesRegex(ValueError, "reviewed without a nonempty relation"):
            self._compare(metrics=metrics, paper_results=papers)

    def test_rejects_a_paper_outside_its_frozen_call_limit(self):
        papers = copy.deepcopy(self.paper_results)
        papers[0]["attempt_count"] = 3
        with self.assertRaisesRegex(ValueError, "frozen authoring-call limit"):
            self._compare(paper_results=papers)


if __name__ == "__main__":
    unittest.main()
