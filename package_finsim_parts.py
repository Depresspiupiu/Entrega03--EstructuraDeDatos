from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


MAX_PART_BYTES = 24_000_000
PART_BUDGET_BYTES = 23_500_000
ARCHIVE_OVERHEAD_BUDGET = 300_000
APP_FOLDER = "FinSimPortable"
LAUNCHER_NAME = "FinSim-Setup.exe"
MANIFEST_NAME = "FinSim-Partes.json"


@dataclass
class ArchivePart:
    files: list[tuple[Path, str, int]] = field(default_factory=list)
    estimated_size: int = 0


def _compressed_size(path: Path) -> int:
    compressor = zlib.compressobj(level=6, wbits=-zlib.MAX_WBITS)
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(compressor.compress(chunk))
    return size + len(compressor.flush()) + 128


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assign_parts(app_dir: Path) -> list[ArchivePart]:
    files = [
        (path, f"{APP_FOLDER}/{path.relative_to(app_dir).as_posix()}", _compressed_size(path))
        for path in app_dir.rglob("*")
        if path.is_file()
    ]
    if not files:
        raise ValueError(f"No hay archivos para empaquetar en {app_dir}.")

    parts: list[ArchivePart] = []
    for path, archive_name, size in sorted(files, key=lambda item: item[2], reverse=True):
        part = min(parts, key=lambda item: item.estimated_size, default=None)
        if part is None or part.estimated_size + size > PART_BUDGET_BYTES:
            part = ArchivePart()
            parts.append(part)
        part.files.append((path, archive_name, size))
        part.estimated_size += size

    for part in parts:
        if part.estimated_size + ARCHIVE_OVERHEAD_BUDGET > MAX_PART_BYTES:
            raise ValueError(
                "Un paquete supera el límite de tamaño previsto; aumenta el número de partes."
            )
    return parts


def _write_parts(parts: list[ArchivePart], output_dir: Path) -> list[dict[str, object]]:
    part_records: list[dict[str, object]] = []
    for index, part in enumerate(parts, start=1):
        filename = f"FinSim-Parte-{index:02d}.zip"
        archive_path = output_dir / filename
        with ZipFile(archive_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for path, archive_name, _ in part.files:
                archive.write(path, archive_name)
        size = archive_path.stat().st_size
        if size > MAX_PART_BYTES:
            raise ValueError(
                f"{filename} pesa {size:,} bytes y supera el límite de {MAX_PART_BYTES:,}."
            )
        part_records.append(
            {
                "name": filename,
                "size": size,
                "sha256": _sha256_file(archive_path),
            }
        )
    return part_records


def _clear_generated_parts(output_dir: Path) -> None:
    for path in output_dir.iterdir():
        if path.is_file() and (
            path.name == MANIFEST_NAME
            or path.name == LAUNCHER_NAME
            or (
                path.name.startswith("FinSim-Parte-")
                and path.suffix.lower() == ".zip"
                and path.stem.removeprefix("FinSim-Parte-").isdigit()
            )
        ):
            path.unlink()


def package(app_dir: Path, launcher: Path, output_dir: Path) -> list[Path]:
    if not app_dir.is_dir():
        raise ValueError(f"No se encontró la carpeta de la aplicación: {app_dir}")
    if not launcher.is_file():
        raise ValueError(f"No se encontró el instalador: {launcher}")
    if launcher.stat().st_size >= MAX_PART_BYTES:
        raise ValueError("FinSim-Setup.exe debe pesar menos de 25 MB.")

    output_dir.mkdir(parents=True, exist_ok=True)
    _clear_generated_parts(output_dir)
    shutil.copy2(launcher, output_dir / LAUNCHER_NAME)

    parts = _assign_parts(app_dir)
    part_records = _write_parts(parts, output_dir)
    build_hash = hashlib.sha256(
        "".join(str(record["sha256"]) for record in part_records).encode("ascii")
    ).hexdigest()
    manifest = {
        "format": 1,
        "build_id": build_hash,
        "app_folder": APP_FOLDER,
        "executable": "FinSimPortable.exe",
        "maximum_part_bytes": MAX_PART_BYTES,
        "parts": part_records,
    }
    manifest_path = output_dir / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    outputs = [output_dir / LAUNCHER_NAME, manifest_path]
    outputs.extend(output_dir / str(record["name"]) for record in part_records)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Empaqueta FinSim en archivos ZIP de menos de 25 MB y un instalador EXE."
    )
    parser.add_argument("--app-dir", type=Path, required=True)
    parser.add_argument("--launcher-exe", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("dist/FinSim-Partes"))
    args = parser.parse_args()

    outputs = package(args.app_dir.resolve(), args.launcher_exe.resolve(), args.output_dir.resolve())
    for path in outputs:
        print(f"{path.name}: {path.stat().st_size / 1_000_000:.2f} MB")
    print(f"Partes generadas: {len(outputs) - 2}")
    print(f"Instalador y partes: {outputs[0].parent}")


if __name__ == "__main__":
    main()
