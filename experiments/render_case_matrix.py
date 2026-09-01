"""Render every canonical episode listed by a completed case-matrix run."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from examples.render_run_log import render_run_log


class CaseMatrixRenderError(ValueError):
    """A case-matrix episode index cannot be rendered without ambiguity."""


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _load_rows(episodes_path: Path) -> Sequence[Mapping[str, Any]]:
    payload = json.loads(episodes_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise CaseMatrixRenderError("episodes.json must contain an object")
    rows = payload.get("episodes")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise CaseMatrixRenderError("episodes.json must contain an episodes array")
    episode_count = payload.get("episode_count")
    if (
        isinstance(episode_count, bool)
        or not isinstance(episode_count, int)
        or episode_count != len(rows)
    ):
        raise CaseMatrixRenderError("episode_count does not match the episodes array")
    return tuple(rows)


def _episode_id(row: Mapping[str, Any]) -> str:
    value = row.get("episode_id")
    if (
        not isinstance(value, str)
        or not value
        or value in (".", "..")
        or Path(value).name != value
    ):
        raise CaseMatrixRenderError("episode_id must be a nonempty file-safe name")
    return value


def _canonical_log_path(
    row: Mapping[str, Any], episodes_path: Path, episode_id: str
) -> Path:
    if row.get("status") != "evaluated":
        raise CaseMatrixRenderError(
            "episode %s is not evaluated; complete the matrix before rendering"
            % episode_id
        )
    value = row.get("log_path")
    if not isinstance(value, str) or not value:
        raise CaseMatrixRenderError("episode %s has no canonical log_path" % episode_id)
    path = Path(value)
    return path if path.is_absolute() else episodes_path.parent / path


def _render_index(
    matrix_name: str,
    rendered: Sequence[Tuple[Mapping[str, Any], str]],
) -> str:
    rows = []
    for row, filename in rendered:
        episode_id = _episode_id(row)
        rows.append(
            "<tr>"
            "<td>%s</td><td><a href=\"%s\">%s</a></td>"
            "<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "</tr>"
            % (
                _escape(row.get("schedule_index")),
                _escape(filename),
                _escape(episode_id),
                _escape(row.get("player_model")),
                _escape(row.get("oracle_model")),
                _escape(row.get("evaluator_model")),
                _escape(row.get("case_family")),
                _escape(row.get("world")),
                _escape(row.get("track")),
                _escape(row.get("repeat")),
                _escape(row.get("active_pass")),
                _escape(row.get("termination_kind")),
            )
        )
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>%s · Role Benchmark matrix</title>
  <style>
    :root { color-scheme: light dark; font-family: ui-sans-serif, system-ui, sans-serif; }
    body { margin: 0; background: Canvas; color: CanvasText; }
    main { width: min(1500px, calc(100%% - 32px)); margin: 0 auto; padding: 24px 0 48px; }
    h1 { margin: 0 0 8px; }
    p { color: color-mix(in srgb, CanvasText 65%%, transparent); }
    .table-wrap { overflow-x: auto; }
    table { width: 100%%; border-collapse: collapse; }
    th, td { padding: 8px; text-align: left; vertical-align: top; border-bottom: 1px solid color-mix(in srgb, CanvasText 16%%, transparent); }
    th { position: sticky; top: 0; background: Canvas; }
    a { color: LinkText; }
  </style>
</head>
<body>
<main>
  <h1>%s</h1>
  <p>%d evaluated episodes. Each link opens the canonical Player–Oracle transcript named by episode ID.</p>
  <div class="table-wrap"><table>
    <thead><tr><th>Schedule</th><th>Episode</th><th>Player</th><th>Oracle</th><th>Evaluator</th><th>Family</th><th>World</th><th>Track</th><th>Repeat</th><th>Pass</th><th>Termination</th></tr></thead>
    <tbody>%s</tbody>
  </table></div>
</main>
</body>
</html>
""" % (
        _escape(matrix_name),
        _escape(matrix_name),
        len(rendered),
        "".join(rows),
    )


def render_case_matrix(episodes_path: Path, output_dir: Path) -> Mapping[str, Any]:
    """Render one new directory from canonical paths in episodes.json only."""

    episodes_path = episodes_path.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise CaseMatrixRenderError("output directory already exists: %s" % output_dir)

    rows = _load_rows(episodes_path)
    seen = set()
    episode_specs: List[Tuple[Mapping[str, Any], Path, str]] = []
    for row in rows:
        episode_id = _episode_id(row)
        if episode_id in seen:
            raise CaseMatrixRenderError("duplicate episode_id %s" % episode_id)
        seen.add(episode_id)
        log_path = _canonical_log_path(row, episodes_path, episode_id)
        episode_specs.append((row, log_path, episode_id + ".html"))

    rendered_pages: List[Tuple[Mapping[str, Any], str, str]] = [
        (row, filename, render_run_log(str(log_path)))
        for row, log_path, filename in episode_specs
    ]

    # Rendering every log before creating the directory avoids a partial output
    # tree when one canonical log is incomplete or malformed.
    output_dir.mkdir(parents=True)
    episode_paths = []
    for _row, filename, document in rendered_pages:
        path = output_dir / filename
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(document)
        episode_paths.append(path)

    index_document = _render_index(
        episodes_path.parent.name,
        tuple((row, filename) for row, filename, _document in rendered_pages),
    )
    index_path = output_dir / "index.html"
    with index_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(index_document)
    return {
        "episode_count": len(episode_paths),
        "episode_paths": tuple(episode_paths),
        "index_path": index_path,
        "output_dir": output_dir,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a completed case-matrix episodes.json to static HTML."
    )
    parser.add_argument("episodes_json", help="Completed matrix episodes.json")
    parser.add_argument("output_dir", help="New directory for episode HTML and index")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = render_case_matrix(Path(args.episodes_json), Path(args.output_dir))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print("%s (%d episodes)" % (result["index_path"], result["episode_count"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
