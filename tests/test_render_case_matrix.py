import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.render_case_matrix import (
    CaseMatrixRenderError,
    render_case_matrix,
)


def episode_row(**updates):
    row = {
        "schedule_index": 1,
        "episode_id": "pendulum__historical__discovery__r05",
        "status": "evaluated",
        "log_path": "episodes/pendulum__historical__discovery__r05.resume-1.jsonl",
        "player_model": "gpt-5.6 <player>",
        "oracle_model": "gpt-5.6 & oracle",
        "evaluator_model": "gpt-5.6 judge",
        "case_family": "pendulum",
        "dataset_kind": "historical_counterfactual",
        "variant_id": "easy",
        "condition_id": "historical",
        "condition_role": "historical",
        "task_setting": "discovery",
        "evaluation_method": "adaptive experimental design",
        "oracle_mode": "deterministic",
        "repeat": 5,
        "active_pass": False,
        "termination_kind": "submitted",
    }
    row.update(updates)
    return row


def write_episode_index(path, rows, *, episode_count=None):
    path.write_text(
        json.dumps(
            {
                "schema": "role_benchmark.case_matrix",
                "episode_count": len(rows) if episode_count is None else episode_count,
                "episodes": rows,
            }
        ),
        encoding="utf-8",
    )


class CaseMatrixRendererTest(unittest.TestCase):
    def test_uses_only_indexed_log_path_and_names_page_by_episode_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "gpt56-matrix"
            episode_dir = run_dir / "episodes"
            episode_dir.mkdir(parents=True)
            canonical = episode_dir / "pendulum__historical__discovery__r05.resume-1.jsonl"
            orphan = episode_dir / "pendulum__historical__discovery__r05.jsonl"
            canonical.write_text("canonical", encoding="utf-8")
            orphan.write_text("abandoned attempt", encoding="utf-8")
            episodes_json = run_dir / "episodes.json"
            write_episode_index(episodes_json, [episode_row()])
            output_dir = root / "rendered"

            with patch(
                "experiments.render_case_matrix.render_run_log",
                return_value="<html><body>canonical transcript</body></html>",
            ) as render:
                result = render_case_matrix(episodes_json, output_dir)

            page = output_dir / "pendulum__historical__discovery__r05.html"
            index = output_dir / "index.html"
            page_text = page.read_text(encoding="utf-8")
            index_text = index.read_text(encoding="utf-8")

        render.assert_called_once_with(str(canonical.resolve()))
        self.assertEqual(result["episode_count"], 1)
        self.assertEqual(result["index_path"], index.resolve())
        self.assertEqual(page_text, "<html><body>canonical transcript</body></html>")
        self.assertIn('href="pendulum__historical__discovery__r05.html"', index_text)
        self.assertNotIn("resume-1.html", index_text)
        self.assertNotIn("abandoned attempt", index_text)
        self.assertIn("gpt-5.6 &lt;player&gt;", index_text)
        self.assertIn("deterministic", index_text)
        self.assertIn("gpt-5.6 judge", index_text)
        self.assertIn("historical_counterfactual", index_text)
        self.assertIn("adaptive experimental design", index_text)

    def test_refuses_existing_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            episodes_json = root / "episodes.json"
            write_episode_index(episodes_json, [])
            output_dir = root / "rendered"
            output_dir.mkdir()

            with self.assertRaisesRegex(
                CaseMatrixRenderError, "output directory already exists"
            ):
                render_case_matrix(episodes_json, output_dir)

    def test_refuses_count_mismatch_duplicate_ids_and_incomplete_matrix(self):
        cases = (
            ("count", [episode_row()], 2, "episode_count does not match"),
            (
                "duplicate",
                [episode_row(), episode_row(schedule_index=2)],
                2,
                "duplicate episode_id",
            ),
            (
                "incomplete",
                [episode_row(status="infrastructure_failed")],
                1,
                "is not evaluated",
            ),
        )
        for label, rows, count, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                episodes_json = root / "episodes.json"
                write_episode_index(episodes_json, rows, episode_count=count)
                with self.assertRaisesRegex(CaseMatrixRenderError, message):
                    render_case_matrix(episodes_json, root / "rendered")


if __name__ == "__main__":
    unittest.main()
