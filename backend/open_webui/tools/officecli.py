"""Safe OfficeCLI tools used by the built-in document assistant."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import mimetypes
import os
import re
import shlex
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from fastapi.responses import HTMLResponse
from starlette.datastructures import Headers

from open_webui.config import (
    LIA_OFFICECLI_BINARY,
    LIA_OFFICECLI_TIMEOUT,
    LIA_OFFICECLI_WORK_DIR,
)
from open_webui.internal.ragflow_client import ragflow_client
from open_webui.internal.ragflow_knowledge import find_dataset
from open_webui.models.chats import Chats
from open_webui.models.files import FileForm, Files
from open_webui.storage.provider import Storage
from open_webui.utils.office_conversion import convert_legacy_word_to_docx

OFFICE_EXTENSIONS = {'.docx', '.xlsx', '.pptx'}
ATTACHABLE_EXTENSIONS = {
    '.png',
    '.jpg',
    '.jpeg',
    '.gif',
    '.webp',
    '.svg',
    '.pdf',
    '.csv',
    '.json',
    '.txt',
    '.md',
    '.zip',
}
STAGE_EXTENSIONS = OFFICE_EXTENSIONS | ATTACHABLE_EXTENSIONS | {'.doc'}
MAX_ATTACHMENTS_PER_CALL = 20
MAX_ATTACHMENT_SIZE = 50 * 1024 * 1024
MAX_ATTACHMENTS_TOTAL_SIZE = 100 * 1024 * 1024
SAFE_COMMANDS = {
    'add',
    'batch',
    'close',
    'create',
    'dump',
    'get',
    'get-marks',
    'goto',
    'help',
    'mark',
    'merge',
    'move',
    'open',
    'query',
    'remove',
    'save',
    'set',
    'swap',
    'unmark',
    'validate',
    'view',
}
FILE_ARGUMENTS = {
    'add': (1,),
    'batch': (1,),
    'close': (1,),
    'create': (1,),
    'dump': (1,),
    'get': (1,),
    'get-marks': (1,),
    'goto': (1,),
    'mark': (1,),
    'merge': (1, 2),
    'move': (1,),
    'open': (1,),
    'query': (1,),
    'remove': (1,),
    'save': (1,),
    'set': (1,),
    'swap': (1,),
    'unmark': (1,),
    'validate': (1,),
    'view': (1,),
}
MIME_TYPES = {
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.md': 'text/markdown',
    '.svg': 'image/svg+xml',
}


def _safe_segment(value: Any, fallback: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(value or '')).strip('._')
    return cleaned[:96] or fallback


def _safe_filename(value: str) -> str:
    filename = Path(value).name.strip()
    filename = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', '_', filename).strip(' .')
    if not filename or filename in {'.', '..'}:
        raise ValueError('Некорректное имя файла')
    return filename[:180]


def _workspace(metadata: dict | None, user: dict | None) -> Path:
    metadata = metadata or {}
    user = user or {}
    user_id = _safe_segment(user.get('id'), 'anonymous')
    chat_id = _safe_segment(metadata.get('chat_id') or metadata.get('session_id'), 'temporary')
    root = Path(LIA_OFFICECLI_WORK_DIR).expanduser().resolve()
    workspace = (root / user_id / chat_id).resolve()
    workspace.relative_to(root)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _binary() -> Path:
    binary = Path(LIA_OFFICECLI_BINARY).expanduser().resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError(
            'OfficeCLI не установлен. Запустите backend/install_officecli.sh или задайте LIA_OFFICECLI_BINARY.'
        )
    return binary


async def _stage_uploaded_files(workspace: Path, metadata: dict | None, user: dict | None) -> list[str]:
    metadata = metadata or {}
    user = user or {}
    staged = []
    for item in metadata.get('files') or []:
        file_id = item.get('id') or item.get('file_id')
        if not file_id:
            continue
        file = await Files.get_file_by_id(str(file_id))
        if not file or (file.user_id != user.get('id') and user.get('role') != 'admin'):
            continue
        filename = _safe_filename(file.filename)
        extension = Path(filename).suffix.lower()
        if extension not in STAGE_EXTENSIONS:
            continue
        destination = workspace / (f'{Path(filename).stem}.docx' if extension == '.doc' else filename)
        if not destination.exists():
            source = Path(await asyncio.to_thread(Storage.get_file, file.path)).resolve()
            if extension == '.doc':
                await asyncio.to_thread(convert_legacy_word_to_docx, source, destination)
            else:
                await asyncio.to_thread(shutil.copy2, source, destination)
        if extension == '.doc':
            # textutil-generated DOCX files are readable by Word and OfficeCLI,
            # but may retain legacy XML ordering that strict OOXML validation
            # reports as schema errors. Keep that provenance for delivery.
            await asyncio.to_thread((workspace / f'.{destination.name}.lia-legacy-doc').touch)
        staged.append(destination.name)

    user_id = str(user.get('id') or '')
    ragflow_sources = metadata.get('ragflow_sources') or []
    selected_sources = [source for source in ragflow_sources if source.get('selected')]
    # A direct UI selection is exact. For a free-form edit request, staging
    # the top five cited documents balances convenience and transfer cost.
    for source in selected_sources or ragflow_sources[:5]:
        dataset_id = str(source.get('dataset_id') or '')
        document_id = str(source.get('document_id') or '')
        if not user_id or not dataset_id or not document_id:
            continue
        try:
            await find_dataset(user_id, dataset_id)
            document = await ragflow_client.get_document(dataset_id, document_id)
            filename = _safe_filename(str(source.get('name') or document.get('name') or document_id))
            extension = Path(filename).suffix.lower()
            if extension not in STAGE_EXTENSIONS:
                continue
            destination = workspace / (f'{Path(filename).stem}.docx' if extension == '.doc' else filename)
            if not destination.exists():
                content, _ = await ragflow_client.download_document(dataset_id, document_id)
                if extension == '.doc':
                    legacy_source = workspace / f'.{document_id}.doc'
                    await asyncio.to_thread(legacy_source.write_bytes, content)
                    try:
                        await asyncio.to_thread(convert_legacy_word_to_docx, legacy_source, destination)
                    finally:
                        legacy_source.unlink(missing_ok=True)
                else:
                    await asyncio.to_thread(destination.write_bytes, content)
            if extension == '.doc':
                await asyncio.to_thread((workspace / f'.{destination.name}.lia-legacy-doc').touch)
            if destination.name not in staged:
                staged.append(destination.name)
        except Exception:
            # Retrieval citations must keep working even if one original was
            # removed or the object store is temporarily unavailable. The
            # Office tool will report that the requested filename is absent.
            continue
    return staged


def _validate_filename_argument(value: str) -> None:
    filename = _safe_filename(value)
    if filename != value or Path(filename).suffix.lower() not in OFFICE_EXTENSIONS:
        raise ValueError('Документ должен находиться в рабочей папке и иметь формат DOCX, XLSX или PPTX')


def _validate_attachment_filename(value: str) -> str:
    filename = _safe_filename(value)
    if filename != value or Path(filename).suffix.lower() not in ATTACHABLE_EXTENSIONS:
        supported = ', '.join(sorted(extension.lstrip('.').upper() for extension in ATTACHABLE_EXTENSIONS))
        raise ValueError(f'Можно прикреплять только файлы из рабочей папки: {supported}')
    return filename


def _validate_token(token: str) -> None:
    if any(ord(char) < 32 for char in token):
        raise ValueError('Управляющие символы в аргументах запрещены')
    if '://' in token or token.startswith(('~', 'file:')):
        raise ValueError('Сетевые и внешние пути в OfficeCLI запрещены')
    if re.match(r'^[A-Za-z]:[\\/]', token):
        raise ValueError('Абсолютные пути в OfficeCLI запрещены')
    if '..' in Path(token.replace('=', '/')).parts:
        raise ValueError('Выход из рабочей папки запрещён')
    allowed_document_paths = (
        '/body',
        '/slide',
        '/Sheet',
        '/sheet',
        '/header',
        '/footer',
        '/comments',
        '/footnotes',
        '/endnotes',
        '/styles',
    )
    if token.startswith('/') and not token.startswith(allowed_document_paths) and token != '/':
        raise ValueError('Абсолютные пути в OfficeCLI запрещены')
    if '=' in token:
        value = token.split('=', 1)[1]
        if value.startswith(('~', 'file:', '/')) or '://' in value:
            raise ValueError('Внешние пути в свойствах OfficeCLI запрещены')


def _validate_command(command: str) -> list[str]:
    if len(command) > 12_000:
        raise ValueError('Команда OfficeCLI слишком длинная')
    args = shlex.split(command, posix=True)
    if not args or args[0] not in SAFE_COMMANDS:
        raise ValueError(f'Недоступная команда OfficeCLI: {args[0] if args else "пустая команда"}')
    if len(args) > 160:
        raise ValueError('Слишком много аргументов OfficeCLI')

    for index in FILE_ARGUMENTS.get(args[0], ()):
        if index >= len(args):
            raise ValueError(f'Для команды {args[0]} не указан документ')
        _validate_filename_argument(args[index])

    for token in args[1:]:
        _validate_token(token)
    return args


async def _run(args: list[str], workspace: Path) -> tuple[int, str, str]:
    env = {
        **os.environ,
        'OFFICECLI_SKIP_UPDATE': '1',
        'OFFICECLI_NO_AUTO_RESIDENT': '1',
    }
    process = await asyncio.create_subprocess_exec(
        str(_binary()),
        *args,
        cwd=str(workspace),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=LIA_OFFICECLI_TIMEOUT)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise RuntimeError(f'OfficeCLI превысил лимит времени {LIA_OFFICECLI_TIMEOUT} секунд')
    return (
        process.returncode or 0,
        stdout.decode('utf-8', 'replace').strip(),
        stderr.decode('utf-8', 'replace').strip(),
    )


async def _emit_status(emitter, description: str, done: bool = False, error: bool = False) -> None:
    if emitter:
        await emitter(
            {
                'type': 'status',
                'data': {
                    'action': 'office_document',
                    'description': description,
                    'done': done,
                    'error': error,
                },
            }
        )


def _office_files(workspace: Path) -> list[str]:
    return sorted(path.name for path in workspace.iterdir() if path.suffix.lower() in OFFICE_EXTENSIONS)


async def office_run(
    command: str,
    __user__: dict = None,
    __metadata__: dict = None,
    __event_emitter__=None,
) -> str:
    """Run one safe OfficeCLI document command inside the current chat workspace.

    Use this for create, inspect, add, set, query, batch, merge and validation operations.
    Uploaded DOC/DOCX/XLSX/PPTX/CSV/JSON/image files are copied into the workspace automatically.
    Legacy DOC files are converted to DOCX and appear in staged_files under the converted name.
    Never use shell syntax; pass only the OfficeCLI arguments after the `officecli` executable.

    :param command: OfficeCLI command, for example `create report.docx` or `view report.docx outline --json`.
    :return: Structured command result and the current list of Office documents.
    """

    workspace = _workspace(__metadata__, __user__)
    staged = await _stage_uploaded_files(workspace, __metadata__, __user__)
    args = _validate_command(command)
    await _emit_status(__event_emitter__, f'Работа с документом: {args[0]}')
    code, stdout, stderr = await _run(args, workspace)
    result = {
        'ok': code == 0,
        'command': args[0],
        'stdout': stdout[-30_000:],
        'stderr': stderr[-8_000:],
        'staged_files': staged,
        'documents': _office_files(workspace),
    }
    await _emit_status(
        __event_emitter__,
        'Операция с документом завершена' if code == 0 else 'OfficeCLI вернул ошибку',
        done=True,
        error=code != 0,
    )
    return json.dumps(result, ensure_ascii=False)


async def office_preview(
    filename: str,
    __user__: dict = None,
    __metadata__: dict = None,
    __event_emitter__=None,
):
    """Render a DOCX, XLSX or PPTX document as an interactive HTML preview in the chat.

    Call this after meaningful edits and before delivery so the user can inspect the result.

    :param filename: Document filename from the current workspace, for example `report.docx`.
    :return: Embedded HTML preview plus a short model-readable status.
    """

    _validate_filename_argument(filename)
    workspace = _workspace(__metadata__, __user__)
    await _stage_uploaded_files(workspace, __metadata__, __user__)
    document = workspace / filename
    if not document.is_file():
        return json.dumps({'ok': False, 'error': f'Документ {filename} не найден'}, ensure_ascii=False)

    preview_name = f'.{document.stem}-{uuid.uuid4().hex[:8]}.html'
    await _emit_status(__event_emitter__, 'Формирую предпросмотр документа')
    code, stdout, stderr = await _run(['view', filename, 'html', '-o', preview_name], workspace)
    preview_path = workspace / preview_name
    if code != 0 or not preview_path.is_file():
        await _emit_status(__event_emitter__, 'Не удалось сформировать предпросмотр', done=True, error=True)
        return json.dumps(
            {'ok': False, 'error': stderr or stdout or 'OfficeCLI не создал HTML-предпросмотр'},
            ensure_ascii=False,
        )

    html = await asyncio.to_thread(preview_path.read_text, encoding='utf-8', errors='replace')
    if len(html.encode('utf-8')) > 8 * 1024 * 1024:
        return json.dumps({'ok': False, 'error': 'HTML-предпросмотр превышает 8 МБ'}, ensure_ascii=False)
    await _emit_status(__event_emitter__, 'Предпросмотр готов', done=True)
    return (
        HTMLResponse(
            content=html,
            headers={'Content-Disposition': f'inline; filename="{preview_name}"'},
        ),
        {'ok': True, 'filename': filename, 'message': 'Предпросмотр документа показан пользователю.'},
    )


async def _register_result(document: Path, user: dict, metadata: dict) -> dict:
    file_id = str(uuid.uuid4())
    name = _safe_filename(document.name)
    storage_name = f'{file_id}_{name}'
    tags = {
        'ЛИА-User-Id': str(user.get('id') or ''),
        'ЛИА-File-Id': file_id,
        'ЛИА-Generated-By': 'officecli',
    }
    with document.open('rb') as source:
        contents, file_path = await asyncio.to_thread(Storage.upload_file, source, storage_name, tags)
    digest = hashlib.sha256(contents).hexdigest()
    content_type = MIME_TYPES.get(document.suffix.lower()) or mimetypes.guess_type(name)[0]
    file_item = await Files.insert_new_file(
        str(user.get('id')),
        FileForm(
            id=file_id,
            filename=name,
            path=file_path,
            hash=digest,
            data={'status': 'completed'},
            meta={
                'name': name,
                'content_type': content_type,
                'size': len(contents),
                'file_hash': digest,
                'data': {
                    'generated_by': 'officecli',
                    'chat_id': metadata.get('chat_id'),
                },
            },
        ),
    )
    if not file_item:
        raise RuntimeError('Не удалось зарегистрировать файл в файловом хранилище ЛИА')
    is_office_document = document.suffix.lower() in OFFICE_EXTENSIONS
    is_image = bool(content_type and content_type.startswith('image/'))
    result = {
        'type': 'image' if is_image else 'file',
        'url': f'/api/v1/files/{file_id}/content' if is_image else file_id,
        'id': file_id,
        'name': name,
        'size': len(contents),
        'content_type': content_type,
    }
    if is_office_document:
        result['office'] = True
    return result


async def _publish_result_files(
    file_items: list[dict],
    metadata: dict,
    event_emitter,
    chat_id: str | None,
    message_id: str | None,
) -> tuple[list[dict], list[dict]]:
    result_files = metadata.setdefault('office_result_files', [])
    new_items = [
        item for item in file_items if not any(current.get('url') == item.get('url') for current in result_files)
    ]
    result_files.extend(new_items)

    if new_items and chat_id and message_id:
        persisted_files = await Chats.add_message_files_by_id_and_message_id(chat_id, message_id, new_items)
        if persisted_files is not None:
            result_files = persisted_files
            metadata['office_result_files'] = persisted_files

    if event_emitter and result_files:
        await event_emitter({'type': 'chat:message:files', 'data': {'files': result_files}})
    return result_files, new_items


def _unique_attachment_names(filenames: list[str]) -> list[str]:
    if not filenames:
        raise ValueError('Не указаны файлы для прикрепления')
    if len(filenames) > MAX_ATTACHMENTS_PER_CALL:
        raise ValueError(f'За один запрос можно прикрепить не более {MAX_ATTACHMENTS_PER_CALL} файлов')

    unique_names = []
    for value in filenames:
        filename = _validate_attachment_filename(value)
        if filename not in unique_names:
            unique_names.append(filename)
    return unique_names


def _resolve_attachments(workspace: Path, filenames: list[str]) -> list[Path]:
    attachments: list[Path] = []
    total_size = 0
    for filename in filenames:
        attachment = workspace / filename
        if attachment.is_symlink() or not attachment.is_file():
            raise ValueError(f'Извлечённый файл {filename} не найден в рабочей папке')
        attachment.resolve().relative_to(workspace.resolve())
        size = attachment.stat().st_size
        if size <= 0:
            raise ValueError(f'Файл {filename} пуст')
        if size > MAX_ATTACHMENT_SIZE:
            raise ValueError(f'Файл {filename} превышает ограничение 50 МБ')
        total_size += size
        attachments.append(attachment)

    if total_size > MAX_ATTACHMENTS_TOTAL_SIZE:
        raise ValueError('Общий размер прикрепляемых файлов превышает 100 МБ')
    return attachments


async def office_attach(
    filenames: list[str],
    __user__: dict = None,
    __metadata__: dict = None,
    __event_emitter__=None,
    __chat_id__: str = None,
    __message_id__: str = None,
) -> str:
    """Attach files extracted from an Office document directly to the assistant response.

    First use office_run with OfficeCLI get/query commands and --save to extract images or other
    assets into the current chat workspace. Then call this tool with the resulting filenames.
    Only PNG/JPG/JPEG/GIF/WEBP/SVG/PDF/CSV/JSON/TXT/MD/ZIP files in the workspace are accepted.

    :param filenames: Extracted workspace filenames to show or download in the chat, up to 20 files.
    :return: Attachment status and registered file metadata.
    """

    metadata = __metadata__ or {}
    user = __user__ or {}
    workspace = _workspace(metadata, user)
    await _stage_uploaded_files(workspace, metadata, user)

    attachments = _resolve_attachments(workspace, _unique_attachment_names(filenames))

    await _emit_status(__event_emitter__, 'Добавляю извлечённые файлы в чат')
    registered = []
    cache = metadata.setdefault('office_delivered_files', {})
    for attachment in attachments:
        cache_key = f'{attachment.resolve()}:{attachment.stat().st_mtime_ns}:{attachment.stat().st_size}'
        file_data = cache.get(cache_key)
        if not file_data:
            file_data = await _register_result(attachment, user, metadata)
            cache[cache_key] = file_data
        registered.append(file_data)

    _, new_items = await _publish_result_files(
        registered,
        metadata,
        __event_emitter__,
        __chat_id__,
        __message_id__,
    )
    await _emit_status(__event_emitter__, 'Извлечённые файлы прикреплены к ответу', done=True)
    return json.dumps(
        {
            'ok': True,
            'files': registered,
            'new_attachments': len(new_items),
            'message': 'Извлечённые файлы уже показаны пользователю в чате.',
        },
        ensure_ascii=False,
    )


async def office_deliver(
    filename: str,
    __user__: dict = None,
    __metadata__: dict = None,
    __event_emitter__=None,
    __chat_id__: str = None,
    __message_id__: str = None,
) -> str:
    """Validate and attach the finished Office document to the assistant response.

    Always call this when the document is ready. The user receives a downloadable file card in chat.

    :param filename: Finished DOCX, XLSX or PPTX filename from the current workspace.
    :return: Delivery status and file metadata.
    """

    _validate_filename_argument(filename)
    metadata = __metadata__ or {}
    user = __user__ or {}
    workspace = _workspace(metadata, user)
    await _stage_uploaded_files(workspace, metadata, user)
    document = workspace / filename
    if not document.is_file():
        return json.dumps({'ok': False, 'error': f'Документ {filename} не найден'}, ensure_ascii=False)

    await _emit_status(__event_emitter__, 'Проверяю и сохраняю итоговый документ')
    code, stdout, stderr = await _run(['validate', filename, '--json'], workspace)
    legacy_converted = (workspace / f'.{document.name}.lia-legacy-doc').is_file()
    if code != 0 and not legacy_converted:
        await _emit_status(__event_emitter__, 'Документ не прошёл проверку', done=True, error=True)
        return json.dumps(
            {'ok': False, 'error': stderr or stdout or 'Документ не прошёл проверку OfficeCLI'},
            ensure_ascii=False,
        )
    validation_warning = None
    if code != 0 and legacy_converted:
        validation_warning = (
            'Документ преобразован из старого формата DOC. Он доступен для редактирования, '
            'но может содержать предупреждения строгой проверки OOXML.'
        )
        await _emit_status(__event_emitter__, validation_warning)

    cache_key = f'{document.resolve()}:{document.stat().st_mtime_ns}:{document.stat().st_size}'
    delivered = metadata.setdefault('office_delivered_files', {})
    file_data = delivered.get(cache_key)
    if not file_data:
        file_data = await _register_result(document, user, metadata)
        delivered[cache_key] = file_data

    await _publish_result_files(
        [file_data],
        metadata,
        __event_emitter__,
        __chat_id__,
        __message_id__,
    )
    await _emit_status(__event_emitter__, 'Документ готов и прикреплён к ответу', done=True)
    return json.dumps(
        {
            'ok': True,
            'filename': filename,
            'file_id': file_data['id'],
            'message': 'Готовый документ прикреплён к ответу пользователя.',
            **({'warning': validation_warning} if validation_warning else {}),
        },
        ensure_ascii=False,
    )


async def ragflow_save_office_document(
    filename: str,
    dataset_id: str,
    __user__: dict = None,
    __metadata__: dict = None,
    __event_emitter__=None,
) -> str:
    """Save an edited Office document as a new document in a RAGFlow knowledge base.

    Use only after office_preview and office_deliver, and only when the user
    explicitly asks to save the result to a knowledge base. The original
    RAGFlow document is preserved; the uploaded result is parsed as a new
    version.

    :param filename: Finished DOCX, XLSX or PPTX filename in the current workspace.
    :param dataset_id: Target RAGFlow dataset ID shown in the source context.
    :return: Uploaded document IDs and parsing status.
    """

    _validate_filename_argument(filename)
    metadata = __metadata__ or {}
    user = __user__ or {}
    user_id = str(user.get('id') or '')
    if not user_id:
        return json.dumps({'ok': False, 'error': 'Пользователь не определён'}, ensure_ascii=False)

    await find_dataset(user_id, dataset_id)
    workspace = _workspace(metadata, user)
    await _stage_uploaded_files(workspace, metadata, user)
    document = workspace / filename
    if not document.is_file():
        return json.dumps({'ok': False, 'error': f'Документ {filename} не найден'}, ensure_ascii=False)

    await _emit_status(__event_emitter__, 'Сохраняю новую версию в базе знаний')
    content = await asyncio.to_thread(document.read_bytes)
    content_type = MIME_TYPES.get(document.suffix.lower()) or 'application/octet-stream'
    upload = UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        size=len(content),
        headers=Headers({'content-type': content_type}),
    )
    uploaded = await ragflow_client.upload_document(dataset_id, upload)
    document_ids = [str(item.get('id')) for item in uploaded if item.get('id')]
    if not document_ids:
        await _emit_status(__event_emitter__, 'RAGFlow не вернул идентификатор документа', done=True, error=True)
        return json.dumps({'ok': False, 'error': 'RAGFlow не вернул идентификатор документа'}, ensure_ascii=False)

    await ragflow_client.parse_documents(dataset_id, document_ids)
    await _emit_status(__event_emitter__, 'Новая версия загружена, индексация запущена', done=True)
    return json.dumps(
        {
            'ok': True,
            'filename': filename,
            'dataset_id': dataset_id,
            'document_ids': document_ids,
            'parsing_started': True,
            'message': 'Новая версия сохранена в базе знаний. Оригинал не изменён.',
        },
        ensure_ascii=False,
    )
