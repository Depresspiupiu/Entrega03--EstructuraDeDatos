import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from launch_finsim import InstallationError, _extract_parts, _load_manifest
from package_finsim_parts import MAX_PART_BYTES, package


class FinSimPackagingTests(unittest.TestCase):
    def test_package_parts_round_trip_below_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            app_dir = root / "FinSimPortable"
            app_dir.mkdir()
            executable_contents = b"standalone executable"
            binary_contents = bytes(range(256)) * 2048
            (app_dir / "FinSimPortable.exe").write_bytes(executable_contents)
            internal = app_dir / "_internal"
            internal.mkdir()
            (internal / "runtime.bin").write_bytes(binary_contents)

            launcher = root / "launcher.exe"
            launcher.write_bytes(b"small setup executable")
            output_dir = root / "release"
            outputs = package(app_dir, launcher, output_dir)

            self.assertTrue(outputs)
            self.assertLess((output_dir / "FinSim-Setup.exe").stat().st_size, MAX_PART_BYTES)
            for archive_path in output_dir.glob("FinSim-Parte-*.zip"):
                self.assertLess(archive_path.stat().st_size, MAX_PART_BYTES)
                with zipfile.ZipFile(archive_path) as archive:
                    self.assertIsNone(archive.testzip())

            build_id, part_paths = _load_manifest(output_dir)
            self.assertTrue(build_id)
            with tempfile.TemporaryDirectory() as extraction_directory:
                _extract_parts(part_paths, Path(extraction_directory))
                extracted_runtime = Path(extraction_directory) / "FinSimPortable"
                self.assertEqual(
                    (extracted_runtime / "FinSimPortable.exe").read_bytes(),
                    executable_contents,
                )
                self.assertEqual(
                    (extracted_runtime / "_internal" / "runtime.bin").read_bytes(),
                    binary_contents,
                )

    def test_rejects_archive_entries_outside_app_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_path = root / "FinSim-Parte-01.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../outside.txt", "unexpected")

            with self.assertRaises(InstallationError):
                _extract_parts([archive_path], root / "extract")


if __name__ == "__main__":
    unittest.main()
