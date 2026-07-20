"""Async adapter for the public RAGFlow 0.24 knowledge-base and chat APIs."""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp
from fastapi import HTTPException, UploadFile
from open_webui.config import RAGFLOW_API_KEY, RAGFLOW_URL
from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL

log = logging.getLogger(__name__)

RAGFLOW_FILENAME_MAX_BYTES = 255
RAGFLOW_MULTIPART_FILENAME_MAX_BYTES = 200

_CYRILLIC_TRANSLITERATION = {
    'а': 'a',
    'б': 'b',
    'в': 'v',
    'г': 'g',
    'д': 'd',
    'е': 'e',
    'ё': 'e',
    'ж': 'zh',
    'з': 'z',
    'и': 'i',
    'й': 'i',
    'к': 'k',
    'л': 'l',
    'м': 'm',
    'н': 'n',
    'о': 'o',
    'п': 'p',
    'р': 'r',
    'с': 's',
    'т': 't',
    'у': 'u',
    'ф': 'f',
    'х': 'h',
    'ц': 'ts',
    'ч': 'ch',
    'ш': 'sh',
    'щ': 'sch',
    'ъ': '',
    'ы': 'y',
    'ь': '',
    'э': 'e',
    'ю': 'yu',
    'я': 'ya',
}


def _truncate_utf8(value: str, max_bytes: int) -> str:
    result: list[str] = []
    size = 0
    for char in value:
        char_size = len(char.encode('utf-8'))
        if size + char_size > max_bytes:
            break
        result.append(char)
        size += char_size
    return ''.join(result)


def _ascii_filename(value: str) -> str:
    transliterated: list[str] = []
    for char in value:
        replacement = _CYRILLIC_TRANSLITERATION.get(char.lower())
        if replacement is None:
            transliterated.append(char)
        elif char.isupper() and replacement:
            transliterated.append(replacement[0].upper() + replacement[1:])
        else:
            transliterated.append(replacement)

    ascii_value = unicodedata.normalize('NFKD', ''.join(transliterated)).encode('ascii', 'ignore').decode('ascii')
    ascii_value = re.sub(r'[^A-Za-z0-9._-]+', '-', ascii_value)
    ascii_value = re.sub(r'-{2,}', '-', ascii_value)
    return ascii_value.strip(' ._-')


def safe_ragflow_filename(filename: str | None) -> str:
    """Return an ASCII multipart filename accepted by RAGFlow 0.24.

    aiohttp percent-encodes non-ASCII characters in Content-Disposition. RAGFlow
    0.24 validates that encoded value, so a 255-byte Cyrillic name can arrive as
    a much longer string. Keeping the transport name ASCII avoids that expansion.
    """
    original = unicodedata.normalize('NFC', (filename or 'document').strip())
    original = original.replace('\\', '/').rsplit('/', 1)[-1]
    original = ''.join('_' if ord(char) < 32 else char for char in original).strip(' .') or 'document'
    if (
        original.isascii()
        and re.fullmatch(r'[A-Za-z0-9._-]+', original)
        and len(original.encode('ascii')) <= RAGFLOW_MULTIPART_FILENAME_MAX_BYTES
    ):
        return original

    original_suffix = Path(original).suffix
    original_stem = original[: -len(original_suffix)] if original_suffix else original
    stem = _ascii_filename(original_stem) or 'document'
    ascii_extension = _ascii_filename(original_suffix.lstrip('.'))
    suffix = f'.{_truncate_utf8(ascii_extension, 15)}' if ascii_extension else ''
    digest = hashlib.sha256(original.encode('utf-8')).hexdigest()[:8]
    tail = f'-{digest}{suffix}'
    stem_budget = RAGFLOW_MULTIPART_FILENAME_MAX_BYTES - len(tail.encode('ascii'))
    shortened_stem = _truncate_utf8(stem, stem_budget).rstrip(' ._-') or 'document'
    safe_name = f'{shortened_stem}{tail}'

    # Keep this guard close to the multipart boundary in case the rules above change later.
    while len(safe_name.encode('ascii')) > RAGFLOW_MULTIPART_FILENAME_MAX_BYTES and shortened_stem:
        shortened_stem = shortened_stem[:-1]
        safe_name = f'{shortened_stem.rstrip(" ._-") or "document"}{tail}'
    return safe_name


def is_ragflow_configured() -> bool:
    return bool(RAGFLOW_URL and RAGFLOW_API_KEY)


def ragflow_base_url() -> str:
    value = RAGFLOW_URL.strip().rstrip('/')
    if value.endswith('/api/v1'):
        value = value[: -len('/api/v1')]
    return value


class RAGFlowClient:
    """Version-pinned RAGFlow 0.24 client used by LIA knowledge agents."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base_url = (base_url or ragflow_base_url()).rstrip('/')
        self.api_key = api_key if api_key is not None else RAGFLOW_API_KEY

    def _ensure_configured(self) -> None:
        if not self.base_url or not self.api_key:
            raise HTTPException(status_code=503, detail='RAGFlow is not configured')

    def _headers(self, *, json_content: bool = True) -> dict[str, str]:
        headers = {'Authorization': f'Bearer {self.api_key}'}
        if json_content:
            headers['Content-Type'] = 'application/json'
        return headers

    async def request(
        self,
        method: str,
        endpoint: str,
        *,
        allow_null_data: bool = False,
        timeout: aiohttp.ClientTimeout | None = None,
        **kwargs: Any,
    ) -> Any:
        self._ensure_configured()
        request_timeout = timeout or aiohttp.ClientTimeout(total=45, sock_connect=10)
        try:
            async with aiohttp.ClientSession(trust_env=False, timeout=request_timeout) as session:
                async with session.request(
                    method,
                    f'{self.base_url}{endpoint}',
                    headers=self._headers(),
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                    **kwargs,
                ) as response:
                    body = await response.text()
                    if response.status >= 400:
                        raise HTTPException(status_code=response.status, detail=f'RAGFlow API error: {body[:500]}')
                    if not body.strip():
                        return None
                    try:
                        payload = await response.json()
                    except (aiohttp.ContentTypeError, ValueError) as exc:
                        raise HTTPException(status_code=502, detail='RAGFlow returned a non-JSON response') from exc
                    if payload.get('code', 0) != 0:
                        raise HTTPException(
                            status_code=400,
                            detail=f'RAGFlow error {payload.get("code")}: {payload.get("message", "Unknown error")}',
                        )
                    data = payload.get('data')
                    if data is None and not allow_null_data:
                        raise HTTPException(status_code=502, detail='RAGFlow returned an empty response')
                    return data
        except HTTPException:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            log.warning('RAGFlow connection failed: %s', exc)
            raise HTTPException(status_code=503, detail=f'RAGFlow connection error: {exc}') from exc

    async def create_dataset(self, name: str, chunk_method: str = 'naive') -> dict[str, Any]:
        return await self.request('POST', '/api/v1/datasets', json={'name': name, 'chunk_method': chunk_method})

    async def check_connection(self) -> None:
        await self.request('GET', '/api/v1/datasets', params={'page': 1, 'page_size': 1})

    async def update_dataset(self, dataset_id: str, payload: dict[str, Any]) -> Any:
        return await self.request('PUT', f'/api/v1/datasets/{quote(dataset_id, safe="")}', json=payload)

    async def delete_dataset(self, dataset_id: str) -> Any:
        return await self.request('DELETE', '/api/v1/datasets', json={'ids': [dataset_id]}, allow_null_data=True)

    async def list_documents(self, dataset_id: str) -> list[dict[str, Any]]:
        data = await self.request(
            'GET',
            f'/api/v1/datasets/{quote(dataset_id, safe="")}/documents',
            params={'page': 1, 'page_size': 1000},
        )
        if isinstance(data, list):
            return data
        return data.get('docs', []) if isinstance(data, dict) else []

    async def get_document(self, dataset_id: str, document_id: str) -> dict[str, Any]:
        """Return a document only when it belongs to the requested dataset."""

        documents = await self.list_documents(dataset_id)
        document = next((item for item in documents if str(item.get('id')) == str(document_id)), None)
        if not document:
            raise HTTPException(status_code=404, detail='Документ RAGFlow не найден')
        return document

    async def download_document(self, dataset_id: str, document_id: str) -> tuple[bytes, str | None]:
        """Download an original document through the public RAGFlow 0.24 API.

        RAGFlow resolves the dataset/document pair to its MinIO bucket and
        object internally. Keeping that lookup behind RAGFlow avoids exposing
        MinIO credentials to LIA and works for non-local storage backends too.
        """

        self._ensure_configured()
        timeout = aiohttp.ClientTimeout(total=300, sock_connect=30, sock_read=300)
        endpoint = (
            f'/api/v1/datasets/{quote(dataset_id, safe="")}'
            f'/documents/{quote(document_id, safe="")}'
        )
        try:
            async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as session:
                async with session.get(
                    f'{self.base_url}{endpoint}',
                    headers=self._headers(json_content=False),
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as response:
                    payload = await response.read()
                    if response.status >= 400:
                        detail = payload[:500].decode('utf-8', 'replace')
                        raise HTTPException(status_code=response.status, detail=f'RAGFlow API error: {detail}')

                    content_type = response.headers.get('Content-Type')
                    # RAGFlow returns a JSON error envelope with HTTP 200 for
                    # some application-level failures. Never pass that off as
                    # an Office document.
                    if content_type and 'application/json' in content_type.lower():
                        try:
                            error = await response.json()
                        except (aiohttp.ContentTypeError, ValueError):
                            error = None
                        if (
                            isinstance(error, dict)
                            and set(error) == {'code', 'message'}
                            and error.get('code', 0) != 0
                        ):
                            raise HTTPException(
                                status_code=502,
                                detail=f'RAGFlow error {error.get("code")}: {error.get("message", "Download failed")}',
                            )
                    return payload, content_type
        except HTTPException:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise HTTPException(status_code=503, detail=f'RAGFlow download error: {exc}') from exc

    async def upload_document(self, dataset_id: str, file: UploadFile) -> list[dict[str, Any]]:
        self._ensure_configured()
        original_filename = file.filename or 'document'
        upload_filename = safe_ragflow_filename(original_filename)
        if upload_filename != original_filename:
            log.info('Shortened RAGFlow filename from %r to %r', original_filename, upload_filename)
        form = aiohttp.FormData()
        form.add_field(
            'file',
            file.file,
            filename=upload_filename,
            content_type=file.content_type or 'application/octet-stream',
        )
        timeout = aiohttp.ClientTimeout(total=300, sock_connect=30)
        try:
            async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as session:
                async with session.post(
                    f'{self.base_url}/api/v1/datasets/{quote(dataset_id, safe="")}/documents',
                    headers=self._headers(json_content=False),
                    data=form,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as response:
                    body = await response.text()
                    if response.status >= 400:
                        raise HTTPException(status_code=response.status, detail=f'RAGFlow API error: {body[:500]}')
                    payload = await response.json()
                    if payload.get('code', 0) != 0:
                        raise HTTPException(status_code=400, detail=payload.get('message', 'RAGFlow upload failed'))
                    return payload.get('data') or []
        except HTTPException:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise HTTPException(status_code=503, detail=f'RAGFlow upload error: {exc}') from exc

    async def parse_documents(self, dataset_id: str, document_ids: list[str]) -> Any:
        return await self.request(
            'POST',
            f'/api/v1/datasets/{quote(dataset_id, safe="")}/chunks',
            json={'document_ids': document_ids},
            allow_null_data=True,
        )

    async def delete_document(self, dataset_id: str, document_id: str) -> Any:
        return await self.request(
            'DELETE',
            f'/api/v1/datasets/{quote(dataset_id, safe="")}/documents',
            json={'ids': [document_id]},
            allow_null_data=True,
        )

    async def get_document_chunks(self, dataset_id: str, document_id: str) -> list[dict[str, Any]]:
        data = await self.request(
            'GET',
            f'/api/v1/datasets/{quote(dataset_id, safe="")}/documents/{quote(document_id, safe="")}/chunks',
        )
        if isinstance(data, list):
            return data
        return data.get('chunks', []) if isinstance(data, dict) else []

    async def search_datasets(
        self,
        question: str,
        dataset_ids: list[str],
        *,
        top_k: int = 30,
        similarity_threshold: float = 0.2,
        vector_similarity_weight: float = 1.0,
    ) -> list[dict[str, Any]]:
        data = await self.request(
            'POST',
            '/api/v1/retrieval',
            json={
                'question': question,
                'dataset_ids': dataset_ids,
                'top_k': top_k,
                'similarity_threshold': similarity_threshold,
                'vector_similarity_weight': vector_similarity_weight,
            },
        )
        if isinstance(data, list):
            return data
        return data.get('chunks', []) if isinstance(data, dict) else []

    async def create_chat(self, name: str, dataset_ids: list[str]) -> dict[str, Any]:
        return await self.request(
            'POST', '/api/v1/chats', json={'name': name, 'avatar': '', 'dataset_ids': dataset_ids}
        )

    async def update_chat(self, chat_id: str, payload: dict[str, Any]) -> Any:
        return await self.request('PUT', f'/api/v1/chats/{quote(chat_id, safe="")}', json=payload)

    async def delete_chat(self, chat_id: str) -> Any:
        return await self.request('DELETE', '/api/v1/chats', json={'ids': [chat_id]}, allow_null_data=True)

    async def stream_chat_completion(self, chat_id: str, payload: dict[str, Any]) -> AsyncIterator[bytes]:
        self._ensure_configured()
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=None)
        try:
            async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as session:
                async with session.post(
                    f'{self.base_url}/api/v1/chats_openai/{quote(chat_id, safe="")}/chat/completions',
                    headers=self._headers(),
                    json=payload,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as response:
                    if response.status >= 400:
                        body = await response.text()
                        raise HTTPException(status_code=response.status, detail=f'RAGFlow API error: {body[:500]}')
                    async for chunk in response.content.iter_any():
                        if chunk:
                            yield chunk
        except HTTPException:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise HTTPException(status_code=503, detail=f'RAGFlow chat error: {exc}') from exc

    async def chat_completion(self, chat_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_configured()
        timeout = aiohttp.ClientTimeout(total=180, sock_connect=30)
        try:
            async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as session:
                async with session.post(
                    f'{self.base_url}/api/v1/chats_openai/{quote(chat_id, safe="")}/chat/completions',
                    headers=self._headers(),
                    json=payload,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as response:
                    body = await response.text()
                    if response.status >= 400:
                        raise HTTPException(status_code=response.status, detail=f'RAGFlow API error: {body[:500]}')
                    try:
                        return await response.json()
                    except (aiohttp.ContentTypeError, ValueError) as exc:
                        raise HTTPException(status_code=502, detail='RAGFlow returned invalid chat JSON') from exc
        except HTTPException:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise HTTPException(status_code=503, detail=f'RAGFlow chat error: {exc}') from exc


ragflow_client = RAGFlowClient()
