"""Safe local conversion helpers for legacy Microsoft Office documents."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def convert_legacy_word_to_docx(source: str | Path, destination: str | Path) -> Path:
    """Convert a legacy binary ``.doc`` file to ``.docx`` without a shell.

    macOS provides ``textutil`` out of the box. Linux deployments can provide
    LibreOffice/soffice. The explicit argument list keeps filenames from being
    interpreted as commands or options.
    """

    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    if source_path.suffix.lower() != '.doc':
        raise ValueError('Исходный документ должен иметь формат DOC')
    if destination_path.suffix.lower() != '.docx':
        raise ValueError('Результат преобразования должен иметь формат DOCX')
    if not source_path.is_file():
        raise FileNotFoundError(f'Документ не найден: {source_path.name}')

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    textutil = shutil.which('textutil')
    soffice = shutil.which('soffice') or shutil.which('libreoffice')

    if textutil:
        result = subprocess.run(
            [
                textutil,
                '-convert',
                'docx',
                '-output',
                str(destination_path),
                '--',
                str(source_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    elif soffice:
        result = subprocess.run(
            [
                soffice,
                '--headless',
                '--convert-to',
                'docx',
                '--outdir',
                str(destination_path.parent),
                str(source_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        generated = destination_path.parent / f'{source_path.stem}.docx'
        if generated.is_file() and generated != destination_path:
            generated.replace(destination_path)
    else:
        raise RuntimeError(
            'Для преобразования DOC в DOCX требуется системный textutil (macOS) '
            'или LibreOffice.'
        )

    if result.returncode != 0 or not destination_path.is_file():
        details = (result.stderr or result.stdout or '').strip()
        raise RuntimeError(f'Не удалось преобразовать DOC в DOCX: {details or "неизвестная ошибка"}')
    return destination_path
