from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest import mock

import experiments.core160_release as core160_release
from experiments.core160_release import (
    AcceptedTemporalRelease,
    CORE20_TEMPORAL_RELEASE_MANIFEST,
    Core20TemporalRelease,
    load_accepted_temporal_release,
    load_core20_temporal_release,
)
from role_benchmark.cases.source import SourceFamilySpec


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CORE20 = (
    "temporal_source_007",
    "temporal_source_015",
    "temporal_source_024",
    "temporal_source_026",
    "temporal_source_031",
    "temporal_source_1019",
    "temporal_source_1044",
    "temporal_source_1045",
    "temporal_source_1055",
    "temporal_source_2001",
    "temporal_source_2025",
    "temporal_source_2026",
    "temporal_source_2085",
    "temporal_source_2089",
    "temporal_source_3015",
    "temporal_source_3021",
    "temporal_source_3026",
    "temporal_source_3037",
    "temporal_source_3045",
    "temporal_source_3046",
)
EXPECTED_ACCEPTED = EXPECTED_CORE20 + ("temporal_source_3047",)


class Core20TemporalReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.release = load_core20_temporal_release(REPO_ROOT)
        cls.accepted_release = load_accepted_temporal_release(REPO_ROOT)

    def test_all_twenty_one_accepted_families_include_the_extension(self):
        release = self.accepted_release
        self.assertIsInstance(release, AcceptedTemporalRelease)
        self.assertEqual(len(release.records), 21)
        self.assertEqual(release.family_ids, EXPECTED_ACCEPTED)
        self.assertEqual(
            tuple(item.release_order for item in release.records),
            tuple(range(1, 22)),
        )
        self.assertEqual(release.records[-1].family_id, "temporal_source_3047")
        self.assertIsInstance(release.records[-1].spec, SourceFamilySpec)
        self.assertEqual(
            release.records[-1].spec.family,
            "temporal_source_3047",
        )
        self.assertNotIn("temporal_source_3047", self.release.family_ids)

    def test_accepted_release_requires_contiguous_unique_release_order(self):
        manifest = json.loads(
            (REPO_ROOT / CORE20_TEMPORAL_RELEASE_MANIFEST).read_text(
                encoding="utf-8"
            )
        )
        manifest["accepted"][-1]["release_order"] = 22
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "release_manifest.json"
            changed.write_text(json.dumps(manifest), encoding="utf-8")
            with mock.patch.object(
                core160_release,
                "CORE20_TEMPORAL_RELEASE_MANIFEST",
                changed,
            ):
                with self.assertRaisesRegex(
                    core160_release.Core20TemporalReleaseError,
                    "unique and contiguous",
                ):
                    load_accepted_temporal_release(REPO_ROOT)

    def test_accepted_release_checks_core_then_extension_selection_order(self):
        manifest = json.loads(
            (REPO_ROOT / CORE20_TEMPORAL_RELEASE_MANIFEST).read_text(
                encoding="utf-8"
            )
        )
        manifest["selection"]["core20_family_ids"][-2:] = reversed(
            manifest["selection"]["core20_family_ids"][-2:]
        )
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "release_manifest.json"
            changed.write_text(json.dumps(manifest), encoding="utf-8")
            with mock.patch.object(
                core160_release,
                "CORE20_TEMPORAL_RELEASE_MANIFEST",
                changed,
            ):
                with self.assertRaisesRegex(
                    core160_release.Core20TemporalReleaseError,
                    "core20 selection order",
                ):
                    load_accepted_temporal_release(REPO_ROOT)

    def test_release_order_and_identities_are_frozen_and_unique(self):
        release = self.release
        self.assertIsInstance(release, Core20TemporalRelease)
        self.assertEqual(len(release.records), 20)
        self.assertEqual(release.family_ids, EXPECTED_CORE20)
        self.assertEqual(
            tuple(item.release_order for item in release.records),
            tuple(range(1, 21)),
        )
        self.assertEqual(len(set(release.family_ids)), 20)
        self.assertEqual(len(set(release.paper_ids)), 20)
        self.assertEqual(len(set(release.arxiv_versioned_ids)), 20)

    def test_all_records_compile_and_expose_an_immutable_spec_mapping(self):
        release = self.release
        self.assertIsInstance(release.spec_by_family, MappingProxyType)
        self.assertEqual(tuple(release.spec_by_family), EXPECTED_CORE20)
        for record in release.records:
            with self.subTest(family=record.family_id):
                self.assertIsInstance(record.spec, SourceFamilySpec)
                self.assertEqual(record.spec.family, record.family_id)
                self.assertIs(
                    record.spec,
                    release.spec_by_family[record.family_id],
                )
                self.assertGreater(record.source_line_count, 0)
                self.assertEqual(
                    record.source_line_count,
                    len(
                        (record.source_directory / "source_packet.txt")
                        .read_text(encoding="utf-8")
                        .splitlines()
                    ),
                )
                self.assertIsInstance(record.provenance, MappingProxyType)

    def test_source_identity_matches_the_manifest_exactly(self):
        manifest = json.loads(
            (REPO_ROOT / CORE20_TEMPORAL_RELEASE_MANIFEST).read_text(
                encoding="utf-8"
            )
        )
        expected = {
            item["family_id"]: (item["paper_id"], item["source"])
            for item in manifest["accepted"]
            if item["designation"] == "core20"
        }
        for record in self.release.records:
            paper_id, source = expected[record.family_id]
            self.assertEqual(record.paper_id, paper_id)
            self.assertEqual(record.source.citation, source["citation"])
            self.assertEqual(record.source.journal_doi, source["journal_doi"])
            self.assertEqual(
                record.source.arxiv_versioned_id,
                source["arxiv_versioned_id"],
            )
            self.assertEqual(
                record.arxiv_versioned_id,
                source["arxiv_versioned_id"],
            )
            self.assertEqual(record.provenance["source"], source)
            self.assertEqual(record.spec.credits[0].citation, source["citation"])
            self.assertEqual(
                record.spec.credits[0].url,
                "https://doi.org/%s" % source["journal_doi"],
            )
            self.assertIn(
                source["arxiv_versioned_id"],
                record.spec.credits[0].role,
            )

    def test_default_and_explicit_root_load_from_an_arbitrary_cwd(self):
        previous = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as directory:
                os.chdir(directory)
                default_release = load_core20_temporal_release()
                explicit_release = load_core20_temporal_release(REPO_ROOT)
        finally:
            os.chdir(previous)
        self.assertEqual(default_release.family_ids, EXPECTED_CORE20)
        self.assertEqual(explicit_release.family_ids, EXPECTED_CORE20)
        self.assertEqual(default_release.paper_ids, explicit_release.paper_ids)


if __name__ == "__main__":
    unittest.main()
