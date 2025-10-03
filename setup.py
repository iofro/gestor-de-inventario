import argparse
import fnmatch
import os
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set

import PyInstaller.__main__


SEP = ';' if os.name == 'nt' else ':'
ROOT = Path(__file__).resolve().parent


DEFAULT_EXCLUDED_DIR_NAMES = {
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

DEFAULT_EXCLUDED_FILE_NAMES = {
    '.DS_Store',
    '.python-version',
}

DEFAULT_EXCLUDED_SUFFIXES = {
    '.key',
    '.pem',
    '.pub',
    '.pyc',
    '.pyo',
    '.log',
    '.tmp',
}

DEFAULT_EXCLUDED_PREFIXES: Set[str] = set()


@dataclass(frozen=True)
class BuildConfig:
    name: str
    excluded_dir_names: Set[str]
    excluded_file_names: Set[str]
    excluded_suffixes: Set[str]
    excluded_prefixes: Set[str]
    excluded_globs: Set[str]

    @classmethod
    def full(cls) -> "BuildConfig":
        return cls(
            name="full",
            excluded_dir_names=set(DEFAULT_EXCLUDED_DIR_NAMES),
            excluded_file_names=set(DEFAULT_EXCLUDED_FILE_NAMES),
            excluded_suffixes=set(DEFAULT_EXCLUDED_SUFFIXES),
            excluded_prefixes=set(DEFAULT_EXCLUDED_PREFIXES),
            excluded_globs=set(),
        )

    @classmethod
    def update(cls) -> "BuildConfig":
        sensitive_dirs = {
            'artifacts',
            'dte_fallidos',
            'dte_firmados',
            'dtes',
            'dtes_pendientes',
            'logs',
            'tickets',
            'svfe-api-firmador',
        }

        sensitive_files = {
            'config_negocio.json',
            'datos_negocio.json',
            'inventario.db',
            'ultimo_inventario.json',
        }

        sensitive_suffixes = {
            '.bak',
            '.crt',
            '.db',
            '.sqlite',
            '.sqlite3',
        }

        sensitive_prefixes = {
            'dte_firmado',
            'facturas_',
        }

        config = cls.full()
        return cls(
            name="update",
            excluded_dir_names=config.excluded_dir_names | sensitive_dirs,
            excluded_file_names=config.excluded_file_names | sensitive_files,
            excluded_suffixes=config.excluded_suffixes | sensitive_suffixes,
            excluded_prefixes=config.excluded_prefixes | sensitive_prefixes,
            excluded_globs=config.excluded_globs
            | {
                '*.sqlite',
                '*.sqlite3',
                '*.db',
                '*.bak',
            },
        )


def _should_exclude(path: Path, *, is_dir: bool, config: BuildConfig) -> bool:
    if any(part in config.excluded_dir_names for part in path.parts):
        return True

    if not is_dir:
        if path.name in config.excluded_file_names:
            return True
        if any(path.name.startswith(prefix) for prefix in config.excluded_prefixes):
            return True
        if path.suffix.lower() in config.excluded_suffixes:
            return True
        if any(fnmatch.fnmatch(path.name, pattern) for pattern in config.excluded_globs):
            return True

    return False


def _destination_for(path: Path) -> str:
    relative_parent = path.relative_to(ROOT).parent
    if relative_parent == Path('.'):
        return '.'
    return relative_parent.as_posix()


def collect_add_data(root: Path, *, config: BuildConfig) -> Iterable[str]:
    entries: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        current_dir = Path(dirpath)

        # Modificamos dirnames in-place para evitar descender en directorios excluidos
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not _should_exclude(current_dir / dirname, is_dir=True, config=config)
        ]

        for filename in filenames:
            file_path = current_dir / filename
            if _should_exclude(file_path, is_dir=False, config=config):
                continue

            destination = _destination_for(file_path)
            entries.append(f"{file_path}{SEP}{destination}")

    return entries


def build(config: BuildConfig, additional_args: Optional[Sequence[str]] = None) -> None:
    add_data = list(collect_add_data(ROOT, config=config))
    hidden_imports = list(collect_hidden_imports())

    args = [
        'main.py',
        '--name=InventarioFarmacia',
        '--onefile',
        '--windowed',
        *[arg for item in add_data for arg in ('--add-data', item)],
        *[arg for module in hidden_imports for arg in ('--hidden-import', module)],
    ]

    if additional_args:
        args.extend(additional_args)

    PyInstaller.__main__.run(args)


def collect_hidden_imports() -> Iterable[str]:
    modules: List[str] = []
    try:
        import reportlab.graphics.barcode as barcode  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return modules

    for module_info in pkgutil.iter_modules(barcode.__path__, barcode.__name__ + '.'):
        modules.append(module_info.name)

    return modules


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Empaquetador de InventarioFarmacia')
    parser.add_argument(
        '--mode',
        choices=('full', 'update'),
        default='full',
        help=(
            'Selecciona el tipo de build. "full" replica el instalador original. '
            '"update" excluye el firmador y archivos con datos sensibles para '
            'distribuir actualizaciones a clientes.'
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.mode == 'update':
        config = BuildConfig.update()
    else:
        config = BuildConfig.full()

    build(config)


if __name__ == '__main__':
    main()
