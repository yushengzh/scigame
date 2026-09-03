import gzip
import io
import tarfile
import unittest

from role_benchmark.temporal.latex import (
    NoTexSourceError,
    TexDecodeError,
    latex_bundle_from_tar_gz,
)


def _tar_gz(path: str, content: bytes) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        member = tarfile.TarInfo(path)
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
    return output.getvalue()


class SingleGzipLatexTest(unittest.TestCase):
    def test_accepts_single_utf8_tex_with_stable_locator_and_comment_removal(self):
        source = (
            "% retained as an empty source line\n"
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "Efficiency is 90\\%. % remove this comment\n"
            "\\end{document}\n"
        ).encode("utf-8")

        bundle = latex_bundle_from_tar_gz(gzip.compress(source))

        self.assertEqual([item.path for item in bundle.files], ["source.tex"])
        self.assertEqual(bundle.archive_member_paths, ("source.tex",))
        self.assertIn("===== BEGIN FILE: source.tex =====", bundle.merged_text)
        self.assertIn("Efficiency is 90\\%.", bundle.merged_text)
        self.assertNotIn("remove this comment", bundle.merged_text)
        self.assertEqual(
            [
                (item.path, item.merged_line_start, item.merged_line_end)
                for item in bundle.member_locators
            ],
            [("source.tex", 2, 6)],
        )
        self.assertEqual(
            [
                (
                    item.path,
                    item.file_line_start,
                    item.file_line_end,
                    item.global_line_start,
                    item.global_line_end,
                )
                for item in bundle.packet_member_locators
            ],
            [("source.tex", 1, 5, 2, 6)],
        )

    def test_rejects_non_utf8_single_gzip(self):
        with self.assertRaises(TexDecodeError):
            latex_bundle_from_tar_gz(gzip.compress(b"\\documentclass{article}\n\xff"))

    def test_rejects_utf8_gzip_without_tex_document_marker(self):
        with self.assertRaises(NoTexSourceError):
            latex_bundle_from_tar_gz(gzip.compress(b"ordinary UTF-8 prose\n"))

    def test_preserves_tar_gz_compatibility(self):
        bundle = latex_bundle_from_tar_gz(
            _tar_gz("main.tex", b"\\documentclass{article}\n")
        )
        self.assertEqual([item.path for item in bundle.files], ["main.tex"])
        self.assertEqual(bundle.archive_member_paths, ("main.tex",))


if __name__ == "__main__":
    unittest.main()
