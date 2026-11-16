from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


APP_FOLDER = "FinSimPortable"
APP_EXECUTABLE = "FinSimPortable.exe"
MANIFEST_NAME = "FinSim-Partes.json"
INSTALLER_NAME = "FinSim-Setup.exe"
INSTALLER_PART_PREFIX = "FinSim-Parte-"
INSTALLER_PART_SUFFIX = ".zip"
MARKER_NAME = ".finsim-install.json"


class InstallationError(RuntimeError):
    pass


def _show_message(title: str, message: str, *, error: bool = False) -> None:
    icon = 0x10 if error else 0x40
    ctypes.windll.user32.MessageBoxW(None, message, title, icon)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(package_dir: Path) -> tuple[str, list[Path]]:
    manifest_path = package_dir / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InstallationError(
            f"No se pudo leer {MANIFEST_NAME}. Comprueba que descargaste todos "
            "los archivos del instalador."
        ) from exc

    if not isinstance(manifest, dict):
        raise InstallationError("El manifiesto de FinSim no tiene un formato válido.")
    parts = manifest.get("parts")
    build_id = manifest.get("build_id")
    if (
        not isinstance(build_id, str)
        or re.fullmatch(r"[a-fA-F0-9]{64}", build_id) is None
        or not isinstance(parts, list)
        or not parts
    ):
        raise InstallationError("El manifiesto de FinSim está incompleto.")

    part_paths: list[Path] = []
    expected_names: set[str] = set()
    for part in parts:
        if not isinstance(part, dict):
            raise InstallationError("El manifiesto de FinSim contiene una parte inválida.")
        name = part.get("name")
        expected_hash = part.get("sha256")
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not name.startswith(INSTALLER_PART_PREFIX)
            or not name.endswith(INSTALLER_PART_SUFFIX)
            or not isinstance(expected_hash, str)
            or re.fullmatch(r"[a-fA-F0-9]{64}", expected_hash) is None
        ):
            raise InstallationError("El manifiesto de FinSim contiene una parte inválida.")
        if name in expected_names:
            raise InstallationError("El manifiesto de FinSim repite una parte.")
        expected_names.add(name)
        part_path = package_dir / name
        if not part_path.is_file():
            raise InstallationError(f"Falta el archivo {name}.")
        if _sha256_file(part_path).lower() != expected_hash.lower():
            raise InstallationError(
                f"El archivo {name} está incompleto o dañado. Descárgalo de nuevo."
            )
        part_paths.append(part_path)

    return build_id, part_paths


def _extract_parts(parts: list[Path], destination: Path) -> None:
    destination_resolved = destination.resolve()
    for part_path in parts:
        try:
            with zipfile.ZipFile(part_path) as archive:
                for member in archive.infolist():
                    member_path = PurePosixPath(member.filename)
                    if (
                        member_path.is_absolute()
                        or len(member_path.parts) < 2
                        or member_path.parts[0] != APP_FOLDER
                        or any(
                            part in {"", ".", ".."}
                            or ":" in part
                            or "\\" in part
                            for part in member_path.parts
                        )
                    ):
                        raise InstallationError(
                            f"La parte {part_path.name} tiene una ruta inválida."
                        )
                    target = (destination / Path(*member_path.parts)).resolve()
                    if not target.is_relative_to(destination_resolved):
                        raise InstallationError(
                            f"La parte {part_path.name} intenta salir de la carpeta de instalación."
                        )
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            raise InstallationError(
                f"No se pudo extraer {part_path.name}: {exc}"
            ) from exc


def install_and_run(package_dir: Path) -> None:
    build_id, parts = _load_manifest(package_dir)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise InstallationError("Windows no proporcionó la carpeta LOCALAPPDATA.")

    versions_dir = Path(local_app_data) / "FinSim" / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    install_dir = versions_dir / build_id
    runtime_dir = install_dir / APP_FOLDER
    executable = runtime_dir / APP_EXECUTABLE
    marker = install_dir / MARKER_NAME

    installed = False
    try:
        installed = (
            marker.is_file()
            and marker.read_text(encoding="utf-8") == build_id
            and executable.is_file()
        )
    except OSError:
        installed = False
    if not installed:
        if install_dir.exists():
            suffix = 1
            while (versions_dir / f"{build_id}-{suffix}").exists():
                suffix += 1
            install_dir = versions_dir / f"{build_id}-{suffix}"
            runtime_dir = install_dir / APP_FOLDER
            executable = runtime_dir / APP_EXECUTABLE
            marker = install_dir / MARKER_NAME

        staging_dir = Path(tempfile.mkdtemp(prefix="finsim-install-", dir=versions_dir))
        try:
            _extract_parts(parts, staging_dir)
            staged_executable = staging_dir / APP_FOLDER / APP_EXECUTABLE
            if not staged_executable.is_file():
                raise InstallationError(
                    "Las partes no contienen el ejecutable de FinSim. Descarga el paquete completo."
                )
            (staging_dir / MARKER_NAME).write_text(build_id, encoding="utf-8")
            staging_dir.replace(install_dir)
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)

    try:
        subprocess.Popen([str(executable)], cwd=str(runtime_dir), close_fds=True)
    except OSError as exc:
        raise InstallationError(f"No se pudo iniciar FinSim: {exc}") from exc


def main() -> None:
    package_dir = Path(sys.executable).resolve().parent
    try:
        install_and_run(package_dir)
    except (InstallationError, OSError) as exc:
        _show_message(
            "No se pudo iniciar FinSim",
            f"{exc}\n\nDeja FinSim-Setup.exe, {MANIFEST_NAME} y todas las partes "
            "ZIP juntas en la misma carpeta.",
            error=True,
        )


if __name__ == "__main__":
    main()
