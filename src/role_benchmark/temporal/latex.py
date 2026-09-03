"""Text-source ingestion for temporal case extraction.

The arXiv source packet keeps TeX as the required scientific narrative and
adds only inert, UTF-8 textual attachments that can contain reported values.
Binary figures and executable files remain outside this minimal packet.
"""

from __future__ import annotations

import gzip
import io
import json
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Union


_PACKET_FORMATS = {
    ".tex": "latex",
    ".csv": "csv",
    ".tsv": "tsv",
    ".dat": "data",
    ".txt": "text",
}

_STANDALONE_TEX_MARKER = re.compile(
    r"(?m)^[ \t]*\\(?:documentclass|documentstyle|begin[ \t]*\{document\}|"
    r"input(?:[ \t]|\{)|magnification\b|bye\b)"
)


class NoTexSourceError(ValueError):
    """The downloaded arXiv source archive contains no TeX source file."""


class TexDecodeError(ValueError):
    """A required TeX member is not valid UTF-8."""


@dataclass(frozen=True)
class LatexMemberLocator:
    """One member's content range in ``LatexBundle.merged_text``."""

    path: str
    merged_line_start: Optional[int]
    merged_line_end: Optional[int]


@dataclass(frozen=True)
class SourcePacketMemberLocator:
    """One packet member's local and packet-global content coordinates."""

    path: str
    format: str
    file_line_start: Optional[int]
    file_line_end: Optional[int]
    global_line_start: Optional[int]
    global_line_end: Optional[int]


@dataclass(frozen=True)
class LatexSourceFile:
    """One decoded ``.tex`` file from a paper source archive."""

    path: str
    text: str


@dataclass(frozen=True)
class SourcePacketFile:
    """One decoded, non-executable textual member of an arXiv source packet."""

    path: str
    format: str
    text: str


@dataclass(frozen=True)
class FigureEvidenceEntry:
    """One human transcription tied to an exact arXiv source asset."""

    source_asset: str
    transcription: str
    semantics: str

    def __post_init__(self) -> None:
        for name, value in (
            ("source_asset", self.source_asset),
            ("transcription", self.transcription),
            ("semantics", self.semantics),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("figure evidence %s must be non-empty text" % name)


@dataclass(frozen=True)
class FigureEvidenceAddendum:
    """Reviewer-authored text for facts visible only in source figures."""

    reviewer: str
    entries: Tuple[FigureEvidenceEntry, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.reviewer, str) or not self.reviewer.strip():
            raise ValueError("figure evidence reviewer must be non-empty text")
        if not self.entries or any(
            not isinstance(item, FigureEvidenceEntry) for item in self.entries
        ):
            raise ValueError("figure evidence entries must be non-empty")


@dataclass(frozen=True)
class LatexBundle:
    """Legacy TeX merge plus the broader textual source packet.

    ``files``, ``merged_text``, and ``member_locators`` retain their TeX-only
    meaning for existing callers.  ``packet_*`` adds safe textual attachments
    without making a data file pretend to be LaTeX.
    """

    files: Tuple[LatexSourceFile, ...]
    merged_text: str
    member_locators: Tuple[LatexMemberLocator, ...] = ()
    packet_files: Tuple[SourcePacketFile, ...] = ()
    packet_text: str = ""
    packet_member_locators: Tuple[SourcePacketMemberLocator, ...] = ()
    archive_member_paths: Tuple[str, ...] = ()

    @property
    def source_packet_text(self) -> str:
        """Return the expanded packet, or the legacy TeX merge when absent."""

        return self.packet_text or self.merged_text

    @property
    def source_packet_files(self) -> Tuple[SourcePacketFile, ...]:
        """Return packet members with a TeX-only fallback for old fixtures."""

        if self.packet_files:
            return self.packet_files
        return tuple(
            SourcePacketFile(path=item.path, format="latex", text=item.text)
            for item in self.files
        )


def _without_comment(line: str) -> str:
    for index, character in enumerate(line):
        if character != "%":
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return line[:index]
    return line


def normalize_latex(source: str) -> str:
    """Remove comments and incidental whitespace without rewriting TeX content."""

    if not isinstance(source, str) or not source.strip():
        raise ValueError("LaTeX source must be non-empty text")
    lines = []
    previous_blank = False
    for raw_line in source.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _without_comment(raw_line).rstrip()
        blank = not line.strip()
        if blank and previous_blank:
            continue
        lines.append("" if blank else line)
        previous_blank = blank
    normalized = "\n".join(lines).strip()
    if not normalized:
        raise ValueError("LaTeX source contains no content after normalization")
    return normalized + "\n"


def load_latex(path: Union[str, Path]) -> str:
    """Read and normalize one UTF-8 ``.tex`` source file."""

    source_path = Path(path)
    if source_path.suffix.lower() != ".tex":
        raise ValueError("temporal source must be one .tex file")
    return normalize_latex(source_path.read_text(encoding="utf-8"))


def normalize_source_packet(source: str) -> str:
    """Canonicalize line endings without rewriting packet evidence.

    Unlike ``normalize_latex``, this function does not treat percent signs in
    CSV, TSV, DAT, or TXT members as TeX comments.  The acquisition renderer
    has already established explicit file boundaries and one global line
    coordinate system, so preserving its lines keeps locators replayable.
    """

    if not isinstance(source, str) or not source.strip():
        raise ValueError("source packet must be non-empty text")
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.rstrip("\n") + "\n"


def load_source_packet(path: Union[str, Path]) -> str:
    """Read one already-rendered UTF-8 textual source packet."""

    return normalize_source_packet(Path(path).read_text(encoding="utf-8"))


def _decode_text(payload: bytes, *, path: str, required: bool) -> Optional[str]:
    try:
        decoded = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        if required:
            raise TexDecodeError(
                "arXiv TeX member %s is not valid UTF-8" % path
            ) from exc
        return None
    return decoded.replace("\r\n", "\n").replace("\r", "\n")


def _strip_tex_comments_preserving_lines(source: str) -> str:
    """Remove non-rendered TeX comments without changing line coordinates."""

    lines = tuple(_without_comment(line).rstrip() for line in source.split("\n"))
    return "\n".join(lines)


def _merge_packet_files(
    files: Tuple[SourcePacketFile, ...],
) -> Tuple[str, Tuple[SourcePacketMemberLocator, ...]]:
    merged_lines = []
    locators = []
    for source in files:
        if merged_lines:
            merged_lines.append("")
        merged_lines.append("===== BEGIN FILE: %s =====" % source.path)
        content = source.text.rstrip("\n").splitlines()
        if content:
            global_start = len(merged_lines) + 1
            merged_lines.extend(content)
            global_end = len(merged_lines)
            file_start = 1
            file_end = len(content)
        else:
            global_start = None
            global_end = None
            file_start = None
            file_end = None
        merged_lines.append("===== END FILE: %s =====" % source.path)
        locators.append(
            SourcePacketMemberLocator(
                path=source.path,
                format=source.format,
                file_line_start=file_start,
                file_line_end=file_end,
                global_line_start=global_start,
                global_line_end=global_end,
            )
        )
    return "\n".join(merged_lines) + "\n", tuple(locators)


def append_figure_evidence_addendum(
    bundle: LatexBundle,
    addendum: FigureEvidenceAddendum,
) -> LatexBundle:
    """Append one reviewed figure transcription to a textual source packet.

    The function only accepts exact filenames present in the fixed arXiv
    archive.  It does not inspect the figure, infer values, or execute code.
    The human-authored record is rendered as ordinary JSON text and receives
    the same deterministic packet-global line coordinates as source members.
    """

    if not isinstance(bundle, LatexBundle):
        raise ValueError("bundle must be a LatexBundle")
    if not isinstance(addendum, FigureEvidenceAddendum):
        raise ValueError("addendum must be FigureEvidenceAddendum")
    available = set(bundle.archive_member_paths)
    for entry in addendum.entries:
        if entry.source_asset not in available:
            raise ValueError(
                "figure evidence source_asset is not in the fixed arXiv archive: %s"
                % entry.source_asset
            )
    addendum_path = "reviewer_figure_evidence.txt"
    if addendum_path in {item.path for item in bundle.source_packet_files}:
        raise ValueError("source archive already uses reserved addendum filename")
    payload = {
        "entries": [
            {
                "semantics": item.semantics.strip(),
                "source_asset": item.source_asset.strip(),
                "transcription": item.transcription.strip(),
            }
            for item in addendum.entries
        ],
        "kind": "reviewer_figure_evidence",
        "reviewer": addendum.reviewer.strip(),
    }
    addendum_file = SourcePacketFile(
        path=addendum_path,
        format="reviewer_figure_evidence",
        text=json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    packet_files = bundle.source_packet_files + (addendum_file,)
    packet_text, packet_locators = _merge_packet_files(packet_files)
    return LatexBundle(
        files=bundle.files,
        merged_text=bundle.merged_text,
        member_locators=bundle.member_locators,
        packet_files=packet_files,
        packet_text=packet_text,
        packet_member_locators=packet_locators,
        archive_member_paths=bundle.archive_member_paths,
    )


def _latex_bundle_from_packet_files(
    packet_files: Tuple[SourcePacketFile, ...],
    *,
    archive_member_paths: Tuple[str, ...],
) -> LatexBundle:
    tex_packet_files = tuple(
        item for item in packet_files if item.format == "latex"
    )
    if not tex_packet_files:
        raise NoTexSourceError("arXiv source archive contains no .tex files")
    files = tuple(
        LatexSourceFile(path=item.path, text=item.text)
        for item in tex_packet_files
    )
    tex_text, tex_packet_locators = _merge_packet_files(tex_packet_files)
    packet_text, packet_locators = _merge_packet_files(packet_files)
    return LatexBundle(
        files=files,
        merged_text=tex_text,
        member_locators=tuple(
            LatexMemberLocator(
                item.path, item.global_line_start, item.global_line_end
            )
            for item in tex_packet_locators
        ),
        packet_files=packet_files,
        packet_text=packet_text,
        packet_member_locators=packet_locators,
        archive_member_paths=archive_member_paths,
    )


def _latex_bundle_from_single_gzip(payload: bytes) -> LatexBundle:
    try:
        uncompressed = gzip.decompress(payload)
    except (gzip.BadGzipFile, EOFError, OSError) as exc:
        raise ValueError(
            "arXiv source is neither a valid gzip-compressed tar archive nor "
            "a valid gzip-compressed single TeX file"
        ) from exc
    path = "source.tex"
    decoded = _decode_text(uncompressed, path=path, required=True)
    assert decoded is not None
    if _STANDALONE_TEX_MARKER.search(decoded) is None:
        raise NoTexSourceError(
            "gzip-compressed single file is not recognizable TeX source"
        )
    source = SourcePacketFile(
        path=path,
        format="latex",
        text=_strip_tex_comments_preserving_lines(decoded),
    )
    return _latex_bundle_from_packet_files(
        (source,), archive_member_paths=(path,)
    )


def latex_bundle_from_tar_gz(payload: bytes) -> LatexBundle:
    """Read an arXiv ``tar.gz`` or gzip-compressed single TeX file in memory.

    A paper still needs at least one TeX member.  In addition, UTF-8 CSV, TSV,
    DAT, and TXT members are retained as inert scientific evidence.  Other
    tar members are ignored.  A single gzip member is accepted only when its
    strictly decoded UTF-8 text contains a standalone TeX document marker.
    """

    if not isinstance(payload, bytes) or not payload:
        raise ValueError("arXiv source archive must be non-empty bytes")
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            archive_member_paths = tuple(
                sorted(
                    member.name
                    for member in archive.getmembers()
                    if member.isfile()
                )
            )
            members = sorted(
                (
                    member
                    for member in archive.getmembers()
                    if member.isfile()
                    and Path(member.name).suffix.lower() in _PACKET_FORMATS
                ),
                key=lambda member: member.name,
            )
            packet_files = []
            for member in members:
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                suffix = Path(member.name).suffix.lower()
                decoded = _decode_text(
                    extracted.read(),
                    path=member.name,
                    required=suffix == ".tex",
                )
                if decoded is None:
                    continue
                if suffix == ".tex":
                    decoded = _strip_tex_comments_preserving_lines(decoded)
                packet_files.append(
                    SourcePacketFile(
                        path=member.name,
                        format=_PACKET_FORMATS[suffix],
                        text=decoded,
                    )
                )
    except (tarfile.TarError, EOFError, OSError):
        return _latex_bundle_from_single_gzip(payload)

    return _latex_bundle_from_packet_files(
        tuple(packet_files), archive_member_paths=archive_member_paths
    )


__all__ = [
    "FigureEvidenceAddendum",
    "FigureEvidenceEntry",
    "LatexBundle",
    "LatexMemberLocator",
    "LatexSourceFile",
    "NoTexSourceError",
    "SourcePacketFile",
    "SourcePacketMemberLocator",
    "TexDecodeError",
    "append_figure_evidence_addendum",
    "latex_bundle_from_tar_gz",
    "load_latex",
    "load_source_packet",
    "normalize_latex",
    "normalize_source_packet",
]
