import os
import pkgutil
from pathlib import Path
from typing import Iterable, List

import PyInstaller.__main__


SEP = ';' if os.name == 'nt' else ':'
ROOT = Path(__file__).resolve().parent


EXCLUDED_DIR_NAMES = {
    '.git',
    '.github',
    '.mypy_cache',
    '.pytest_cache',
    '.venv',
    '.vscode',
    '__pycache__',
    'build',
    'dist',
    'node_modules',
    'tests',
}

EXCLUDED_FILE_NAMES = {
    '.DS_Store',
    '.python-version',
}

EXCLUDED_SUFFIXES = {
    '.key',
    '.pem',
    '.pub',
    '.pyc',
    '.pyo',
    '.log',
    '.tmp',
}


def _should_exclude(path: Path, *, is_dir: bool) -> bool:
    if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
        return True

    if not is_dir:
        if path.name in EXCLUDED_FILE_NAMES:
            return True
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            return True

    return False


def _destination_for(path: Path) -> str:
    relative_parent = path.relative_to(ROOT).parent
    if relative_parent == Path('.'):
        return '.'
    return relative_parent.as_posix()


def collect_add_data(root: Path) -> Iterable[str]:
    entries: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        current_dir = Path(dirpath)

        # Modificamos dirnames in-place para evitar descender en directorios excluidos
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not _should_exclude(current_dir / dirname, is_dir=True)
        ]

        for filename in filenames:
            file_path = current_dir / filename
            if _should_exclude(file_path, is_dir=False):
                continue

            destination = _destination_for(file_path)
            entries.append(f"{file_path}{SEP}{destination}")

    return entries


add_data = list(collect_add_data(ROOT))


def collect_hidden_imports() -> Iterable[str]:
    modules: List[str] = []
    try:
        import reportlab.graphics.barcode as barcode  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return modules

    for module_info in pkgutil.iter_modules(barcode.__path__, barcode.__name__ + '.'):
        modules.append(module_info.name)

    return modules


hidden_imports = list(collect_hidden_imports())

PyInstaller.__main__.run([
    'main.py',
    '--name=InventarioFarmacia',
    '--onefile',
    '--windowed',
    *[arg for item in add_data for arg in ('--add-data', item)],
    *[arg for module in hidden_imports for arg in ('--hidden-import', module)],
])
