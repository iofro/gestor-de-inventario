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
    'env',
    'venv',
    '.vscode',
    '__pycache__',
    'build',
    'dist',
    'node_modules',
    'tests',
    'verificador',
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
DEFAULT_EXCLUDED_DIR_GLOBS: Set[str] = {
    '.venv*',
}
DEFAULT_EXCLUDED_RELATIVE_PATHS: Set[Path] = {
    Path('svfe-api-firmador') / 'uploads',
    # Avoid bundling accidental nested copies of the repository.
    Path('repositorio de github'),
}

@dataclass(frozen=True)
class BuildConfig:
    name: str
    excluded_dir_names: Set[str]
    excluded_dir_globs: Set[str]
    excluded_file_names: Set[str]
    excluded_suffixes: Set[str]
    excluded_prefixes: Set[str]
    excluded_globs: Set[str]
    excluded_relative_paths: Set[Path]

    @classmethod
    def full(cls) -> "BuildConfig":
        return cls(
            name="full",
            excluded_dir_names=set(DEFAULT_EXCLUDED_DIR_NAMES),
            excluded_dir_globs=set(DEFAULT_EXCLUDED_DIR_GLOBS),
            excluded_file_names=set(DEFAULT_EXCLUDED_FILE_NAMES),
            excluded_suffixes=set(DEFAULT_EXCLUDED_SUFFIXES),
            excluded_prefixes=set(DEFAULT_EXCLUDED_PREFIXES),
            excluded_globs=set(),
            excluded_relative_paths=set(DEFAULT_EXCLUDED_RELATIVE_PATHS),
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
        }

        sensitive_dir_globs: Set[str] = set()

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
        excluded_relative_paths = set(config.excluded_relative_paths)
        excluded_relative_paths.add(Path('svfe-api-firmador'))

        return cls(
            name="update",
            excluded_dir_names=config.excluded_dir_names | sensitive_dirs,
            excluded_dir_globs=config.excluded_dir_globs | sensitive_dir_globs,
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
            excluded_relative_paths=excluded_relative_paths,
        )

def _should_exclude(path: Path, *, is_dir: bool, config: BuildConfig) -> bool:
    try:
        relative_path = path.relative_to(ROOT)
    except ValueError:
        relative_path = None

    if any(part in config.excluded_dir_names for part in path.parts):
        return True

    if any(
        fnmatch.fnmatch(part, pattern)
        for part in path.parts
        for pattern in config.excluded_dir_globs
    ):
        return True

    if relative_path is not None:
        for excluded in config.excluded_relative_paths:
            if relative_path == excluded:
                return True
            if relative_path.parts[: len(excluded.parts)] == excluded.parts:
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

def build(
    config: BuildConfig,
    *,
    bundle_mode: str = "onedir",
    additional_args: Optional[Sequence[str]] = None,
) -> None:
    add_data = list(collect_add_data(ROOT, config=config))
    hidden_imports = list(collect_hidden_imports())

    args = [
        'main.py',
        '--name=InventarioFarmacia',
        '--windowed',
        *[arg for item in add_data for arg in ('--add-data', item)],
        *[arg for module in hidden_imports for arg in ('--hidden-import', module)],
    ]

    if bundle_mode == 'onefile':
        args.append('--onefile')
    elif bundle_mode == 'onedir':
        args.append('--onedir')
    else:
        raise ValueError(f'Unsupported bundle mode: {bundle_mode}')

    if additional_args:
        args.extend(additional_args)

    PyInstaller.__main__.run(args)

    if bundle_mode == 'onedir':
        expected_exe = ROOT / 'dist' / 'InventarioFarmacia' / 'InventarioFarmacia.exe'
        if not expected_exe.is_file():
            raise RuntimeError(
                'La compilación de PyInstaller no generó dist/InventarioFarmacia/InventarioFarmacia.exe'
            )

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
            '"update" excluye archivos y directorios con datos sensibles para '
            'distribuir actualizaciones a clientes.'
        ),
    )
    parser.add_argument(
        '--bundle',
        choices=('onefile', 'onedir'),
        default='onedir',
        help='Selecciona el modo de empaquetado de PyInstaller.',
    )
    return parser.parse_args()

def main() -> None:
    args = parse_args()
    if args.mode == 'update':
        config = BuildConfig.update()
    else:
        config = BuildConfig.full()

    build(config, bundle_mode=args.bundle)

if __name__ == '__main__':
    main()
