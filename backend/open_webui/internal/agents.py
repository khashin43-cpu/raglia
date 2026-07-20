"""Native ЛИА adapters for LIA system agents."""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp
from fastapi import HTTPException, Request
from open_webui.config import (
    LIA_ARIA_API_BASE_URL,
    LIA_ARIA_API_KEY,
    LIA_ARIA_ENABLED,
    LIA_ARIA_MODEL,
    LIA_LND_API_BASE_URL,
    LIA_LND_API_KEY,
    LIA_LND_ENABLED,
    LIA_OFFICE_ENABLED,
)
from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL
from open_webui.internal.ragflow_client import is_ragflow_configured, ragflow_client
from open_webui.internal.ragflow_knowledge import get_agent, list_agents, list_spaces, sync_agent_chat
from starlette.responses import JSONResponse, StreamingResponse

log = logging.getLogger(__name__)

ARIA_AGENT_ID = 'agent:aria'
OFFICE_AGENT_ID = 'agent:office'
SIP_AGENT_PREFIX = 'agent:sip:'
RAGFLOW_AGENT_PREFIX = 'agent:ragflow:'
SIP_CONSULTANT_MODE = 'chat_lnd'
SIP_CONSULTANT_ID = f'{SIP_AGENT_PREFIX}{SIP_CONSULTANT_MODE}'
SIP_CONSULTANT_NAME = 'Консультант по ЛНАД'
SIP_CONSULTANT_SUGGESTIONS = [
    {
        'title': ['Дресс-код', 'Требования к одежде в офисе'],
        'content': 'Какой дресс-код действует в офисе?',
    },
    {
        'title': ['Командировка', 'План оформления'],
        'content': 'Какой план оформления командировки?',
    },
    {
        'title': ['Суточные расходы', 'Нормы для командировок'],
        'content': 'Какие нормы суточных расходов действуют в командировке?',
    },
    {
        'title': ['Флеш-накопители', 'Политика использования'],
        'content': 'Какова политика использования флеш-накопителей?',
    },
]
OFFICE_AGENT_SUGGESTIONS = [
    {
        'title': ['Презентация', 'Создать с нуля'],
        'content': 'Создай презентацию для руководства. Сначала уточни тему, аудиторию и желаемый объём.',
    },
    {
        'title': ['Документ Word', 'Подготовить отчёт'],
        'content': 'Подготовь профессиональный отчёт в Word. Уточни структуру и исходные данные.',
    },
    {
        'title': ['Таблица Excel', 'Расчёты и аналитика'],
        'content': 'Создай Excel-таблицу с формулами и понятным оформлением. Уточни, какие данные и расчёты нужны.',
    },
    {
        'title': ['Редактирование', 'Загрузить готовый файл'],
        'content': 'Я загружу документ. Изучи его, уточни необходимые изменения и покажи результат перед сохранением.',
    },
]
OFFICE_AGENT_SYSTEM_PROMPT = """Ты — Офисный ассистент ЛИА. Ты создаёшь и редактируешь DOCX, XLSX и PPTX
через встроенные инструменты OfficeCLI, а результат показываешь прямо в чате.

Правила работы:
1. Если задача неоднозначна, сначала коротко уточни цель, аудиторию, стиль и критичные требования.
2. Загруженные пользователем офисные файлы автоматически доступны в рабочей папке чата.
   Старые документы DOC автоматически преобразуются в DOCX; используй имя DOCX из списка staged_files.
3. Используй office_run для чтения и правок. Начинай с `view <файл> outline --json` или `get`,
   а если синтаксис свойства неясен — с `help <формат> <элемент> --json`. Не угадывай параметры.
4. Для больших изменений предпочитай атомарный `batch`. После правок запускай `validate <файл> --json`
   и устраняй найденные ошибки.
5. После существенного результата обязательно вызови office_preview, чтобы пользователь увидел документ в чате.
6. Если пользователь просит извлечь картинки, графики или вложенные файлы из документа, сохрани каждый объект
   в рабочую папку через office_run с параметром `--save`, затем вызови office_attach со списком полученных имён.
   Не вставляй внутренний путь вручную в текст ответа: office_attach сам покажет файлы в чате.
7. Когда результат готов, обязательно вызови office_deliver. Не сообщай о готовности, пока инструмент
   не подтвердил прикрепление файла.
8. Пиши пользователю понятным деловым языком: что сделано, что можно проверить в предпросмотре и какой файл готов.
Не показывай внутренние команды без просьбы пользователя и не пытайся использовать shell или внешние пути.
"""

RAGFLOW_OFFICE_SYSTEM_PROMPT = """Если пользователь просит изменить найденный DOCX, XLSX или PPTX,
используй встроенные инструменты OfficeCLI прямо в этом чате. Исходные документы из приведённых источников
автоматически появятся в рабочей папке под указанными именами. Сначала изучи структуру через office_run,
после правок покажи office_preview и обязательно прикрепи результат через office_deliver. Не изменяй оригинал
молча. Если пользователь явно просит сохранить результат в базу знаний, используй
ragflow_save_office_document: он загрузит отдельную новую версию и запустит её индексацию.
"""


async def get_system_agent_models(user_id: str | None = None) -> list[dict[str, Any]]:
    """Expose Aria, SIP and user knowledge agents in the native chat pipeline."""

    models: list[dict[str, Any]] = []
    if LIA_ARIA_ENABLED and LIA_ARIA_API_BASE_URL:
        models.append(
            {
                'id': ARIA_AGENT_ID,
                'name': 'Ария',
                'object': 'model',
                'created': 0,
                'owned_by': 'agent',
                'connection_type': 'external',
                'agent': {
                    'id': 'aria',
                    'name': 'Ария',
                    'description': 'Универсальный помощник ЛИА.',
                    'provider': 'aria',
                    'system': True,
                },
                'info': {
                    'meta': {
                        'description': 'Универсальный помощник ЛИА.',
                        'agent': True,
                        'agent_id': 'aria',
                        'agent_provider': 'aria',
                        'agent_group': 'system',
                        'capabilities': {
                            'vision': True,
                            'file_upload': True,
                            'file_context': True,
                            'builtin_tools': True,
                            'citations': True,
                            'status_updates': True,
                            'web_search': False,
                            'image_generation': False,
                            'code_interpreter': False,
                        },
                    }
                },
                'tags': [{'name': 'Системный ассистент'}, {'name': 'Ария'}],
            }
        )

    if LIA_OFFICE_ENABLED and LIA_ARIA_ENABLED and LIA_ARIA_API_BASE_URL:
        models.append(
            {
                'id': OFFICE_AGENT_ID,
                'name': 'Офисный ассистент',
                'object': 'model',
                'created': 0,
                'owned_by': 'agent',
                'connection_type': 'external',
                'agent': {
                    'id': 'office',
                    'name': 'Офисный ассистент',
                    'description': 'Создание и редактирование Word, Excel и PowerPoint прямо в чате.',
                    'provider': 'office',
                    'system': True,
                },
                'info': {
                    'meta': {
                        'description': 'Создание и редактирование Word, Excel и PowerPoint прямо в чате.',
                        'agent': True,
                        'agent_id': 'office',
                        'agent_provider': 'office',
                        'agent_group': 'system',
                        'suggestion_prompts': OFFICE_AGENT_SUGGESTIONS,
                        'capabilities': {
                            'vision': False,
                            'file_upload': True,
                            'file_context': True,
                            'builtin_tools': True,
                            'citations': False,
                            'status_updates': True,
                            'web_search': False,
                            'image_generation': False,
                            'code_interpreter': False,
                            'terminal': False,
                        },
                        'builtinTools': {
                            'office': True,
                            'time': False,
                            'knowledge': False,
                            'chats': False,
                            'memory': False,
                            'web_search': False,
                            'image_generation': False,
                            'code_interpreter': False,
                            'notes': False,
                            'channels': False,
                            'tasks': False,
                            'automations': False,
                            'calendar': False,
                        },
                    }
                },
                'tags': [{'name': 'Системный ассистент'}, {'name': 'Документы'}],
            }
        )

    if LIA_LND_ENABLED:
        models.append(
            {
                'id': SIP_CONSULTANT_ID,
                'name': SIP_CONSULTANT_NAME,
                'object': 'model',
                'created': 0,
                'owned_by': 'agent',
                'connection_type': 'external',
                'agent': {
                    'id': 'sip',
                    'name': SIP_CONSULTANT_NAME,
                    'provider': 'sip',
                    'mode': SIP_CONSULTANT_MODE,
                    'system': True,
                },
                'info': {
                    'meta': {
                        'description': 'Консультации по локально-нормативной документации.',
                        'agent': True,
                        'agent_id': 'sip',
                        'agent_provider': 'sip',
                        'agent_group': 'system',
                        'suggestion_prompts': SIP_CONSULTANT_SUGGESTIONS,
                        'capabilities': {
                            'vision': False,
                            'file_upload': False,
                            'web_search': False,
                            'image_generation': False,
                            'code_interpreter': False,
                        },
                    }
                },
                'tags': [{'name': 'Системный ассистент'}, {'name': 'ЛНАД'}],
            }
        )

    if is_ragflow_configured() and user_id:
        try:
            agents = await list_agents(user_id)
            models.extend(
                {
                    'id': f'{RAGFLOW_AGENT_PREFIX}{agent["id"]}',
                    'name': agent.get('name') or agent['id'],
                    'object': 'model',
                    'created': agent.get('created_at', 0),
                    'owned_by': 'agent',
                    'connection_type': 'external',
                    'agent': {
                        'id': agent['id'],
                        'name': agent.get('name') or agent['id'],
                        'description': agent.get('description') or '',
                        'provider': 'ragflow',
                        'owner_id': agent.get('owner_id') or user_id,
                        'model': agent.get('model') or '',
                        'space_ids': agent.get('space_ids') or [],
                        'system': False,
                    },
                    'info': {
                        'meta': {
                            'description': agent.get('description') or '',
                            'agent': True,
                            'agent_id': agent['id'],
                            'agent_provider': 'ragflow',
                            'agent_group': 'user',
                            'capabilities': {
                                'vision': False,
                                'file_upload': True,
                                'file_context': True,
                                'builtin_tools': True,
                                'citations': True,
                                'status_updates': True,
                                'web_search': False,
                                'image_generation': False,
                                'code_interpreter': False,
                            },
                            'builtinTools': {
                                'office': bool(LIA_OFFICE_ENABLED),
                                'time': False,
                                'knowledge': False,
                                'chats': False,
                                'memory': False,
                                'web_search': False,
                                'image_generation': False,
                                'code_interpreter': False,
                                'notes': False,
                                'channels': False,
                                'tasks': False,
                                'automations': False,
                                'calendar': False,
                            },
                        }
                    },
                    'tags': [{'name': 'RAGFlow'}, {'name': 'Ассистент'}],
                }
                for agent in agents
                if agent.get('id') and agent.get('active', True)
            )
        except HTTPException as exc:
            log.warning('Unable to load RAGFlow agents: %s', exc.detail)

    return models


def _lnd_url() -> str:
    base_url = LIA_LND_API_BASE_URL.rstrip('/')
    if base_url.endswith('/chat/completions'):
        return base_url
    return f'{base_url}/chat/completions'


def _aria_url() -> str:
    base_url = LIA_ARIA_API_BASE_URL.rstrip('/')
    if base_url.endswith('/chat/completions') or base_url.endswith('/v1/responses'):
        return base_url
    return f'{base_url}/chat/completions'


def _sip_mode(model_id: str) -> str:
    if model_id != SIP_CONSULTANT_ID:
        raise HTTPException(status_code=400, detail='Unknown LNAD consultant model')
    return SIP_CONSULTANT_MODE


def _prepare_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared = []
    for message in messages:
        role = message.get('role')
        content = message.get('content')
        if role in {'system', 'user', 'assistant'} and content is not None:
            prepared.append({'role': role, 'content': content})
    return prepared


def _prepare_aria_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the OpenAI message fields required by native tool calling."""

    prepared = []
    allowed_fields = (
        'role',
        'content',
        'name',
        'tool_call_id',
        'tool_calls',
        'function_call',
        'refusal',
    )
    for message in messages:
        role = message.get('role')
        if role not in {'developer', 'system', 'user', 'assistant', 'tool'}:
            continue

        item = {field: message[field] for field in allowed_fields if field in message}
        # Assistant tool-call messages are valid with null/omitted content.
        if item.get('content') is None and not item.get('tool_calls') and not item.get('function_call'):
            continue
        prepared.append(item)
    return prepared


def _build_payload(form_data: dict[str, Any], mode: str) -> dict[str, Any]:
    params = form_data.get('params') or {}
    payload: dict[str, Any] = {
        'model': mode,
        'messages': _prepare_messages(form_data.get('messages') or []),
        'temperature': form_data.get('temperature', params.get('temperature', 0.01)),
        'stream': bool(form_data.get('stream', True)),
    }

    max_tokens = form_data.get('max_tokens', params.get('max_tokens'))
    if max_tokens:
        payload['max_tokens'] = max_tokens
    return payload


def _build_aria_payload(
    form_data: dict[str, Any],
    additional_system_prompt: str | None = None,
) -> dict[str, Any]:
    params = form_data.get('params') or {}
    messages = _prepare_aria_messages(form_data.get('messages') or [])
    messages.insert(
        0,
        {
            'role': 'system',
            'content': (
                'Когда пользователь просит создать изображение, схему, график, диаграмму '
                'или интерактивный макет, возвращай результат в fenced-коде с языком html, '
                'svg, mermaid, vega или vega-lite. HTML и SVG должны быть самодостаточными.'
            ),
        },
    )
    if additional_system_prompt:
        messages.insert(0, {'role': 'system', 'content': additional_system_prompt})
    payload: dict[str, Any] = {
        'model': LIA_ARIA_MODEL,
        'messages': messages,
        'temperature': form_data.get('temperature', params.get('temperature', 0.4)),
        'stream': bool(form_data.get('stream', True)),
    }
    for name in (
        'max_tokens',
        'max_completion_tokens',
        'top_p',
        'frequency_penalty',
        'presence_penalty',
        'seed',
        'stop',
        'logit_bias',
        'logprobs',
        'top_logprobs',
        'n',
        'response_format',
        'reasoning_effort',
        'tools',
        'tool_choice',
        'parallel_tool_calls',
        'stream_options',
        'user',
    ):
        value = form_data.get(name, params.get(name))
        if value is not None and value != []:
            payload[name] = value
    return payload


def _headers() -> dict[str, str]:
    headers = {'Content-Type': 'application/json'}
    if LIA_LND_API_KEY:
        headers['Authorization'] = f'Bearer {LIA_LND_API_KEY}'
    return headers


def _aria_headers() -> dict[str, str]:
    headers = {'Content-Type': 'application/json'}
    if LIA_ARIA_API_KEY:
        headers['Authorization'] = f'Bearer {LIA_ARIA_API_KEY}'
    return headers


def _error_event(message: str) -> str:
    return f'data: {json.dumps({"error": {"message": message}}, ensure_ascii=False)}\n\n'


def _completion_events(text: str, provider: str = 'SIP') -> list[str]:
    """Convert a non-stream OpenAI response into native SSE delta events."""

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [_error_event(f'Invalid {provider} response: {exc}'), 'data: [DONE]\n\n']

    choice = data.get('choices', [{}])[0]
    message = choice.get('message', {})
    content = message.get('content', '') or ''
    tool_calls = message.get('tool_calls') or []
    if not content and not tool_calls:
        return [
            f'data: {json.dumps(data, ensure_ascii=False)}\n\n',
            'data: [DONE]\n\n',
        ]

    events = []
    for offset in range(0, len(content), 180):
        chunk = {'choices': [{'delta': {'content': content[offset : offset + 180]}}]}
        events.append(f'data: {json.dumps(chunk, ensure_ascii=False)}\n\n')

    if tool_calls:
        normalized_tool_calls = [
            {**tool_call, 'index': tool_call.get('index', index)} for index, tool_call in enumerate(tool_calls)
        ]
        chunk = {
            'choices': [
                {
                    'delta': {'tool_calls': normalized_tool_calls},
                    'finish_reason': choice.get('finish_reason') or 'tool_calls',
                }
            ]
        }
        events.append(f'data: {json.dumps(chunk, ensure_ascii=False)}\n\n')
    events.append('data: [DONE]\n\n')
    return events


async def _iter_complete_stream_lines(stream):
    """Yield complete upstream SSE lines regardless of TCP chunk boundaries.

    ``aiohttp.StreamReader.iter_any`` deliberately returns whatever bytes are
    currently available. A chunk can therefore contain half an SSE JSON event
    or several events at once. The chat middleware consumes one SSE line per
    iterator item, so forwarding those raw chunks drops arbitrary token pieces.
    """

    buffer = bytearray()
    async for chunk in stream.iter_any():
        if not chunk:
            continue
        buffer.extend(chunk)

        while True:
            newline = buffer.find(b'\n')
            if newline < 0:
                break
            line = bytes(buffer[:newline]).rstrip(b'\r')
            del buffer[: newline + 1]
            if line.strip():
                yield line + b'\n'

    trailing = bytes(buffer).rstrip(b'\r')
    if trailing.strip():
        yield trailing + b'\n'


async def _stream_sip(payload: dict[str, Any]):
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=None)
    try:
        async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as session:
            async with session.post(
                _lnd_url(),
                headers=_headers(),
                json=payload,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as response:
                if response.status == 405:
                    fallback_payload = {**payload, 'stream': False}
                    async with session.post(
                        _lnd_url(),
                        headers=_headers(),
                        json=fallback_payload,
                        ssl=AIOHTTP_CLIENT_SESSION_SSL,
                    ) as fallback_response:
                        text = await fallback_response.text()
                        if fallback_response.status >= 400:
                            yield _error_event(text[:500])
                            yield 'data: [DONE]\n\n'
                        else:
                            for event in _completion_events(text):
                                yield event
                    return

                if response.status >= 400:
                    text = await response.text()
                    yield _error_event(text[:500])
                    yield 'data: [DONE]\n\n'
                    return

                content_type = response.headers.get('Content-Type', '')
                if 'application/json' in content_type:
                    text = await response.text()
                    for event in _completion_events(text):
                        yield event
                    return

                async for line in _iter_complete_stream_lines(response.content):
                    yield line
    except (aiohttp.ClientError, TimeoutError) as exc:
        log.error('SIP agent connection error: %s', exc, exc_info=True)
        yield _error_event(str(exc))
        yield 'data: [DONE]\n\n'


async def _stream_aria(payload: dict[str, Any]):
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=None)
    try:
        async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as session:
            async with session.post(
                _aria_url(),
                headers=_aria_headers(),
                json=payload,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as response:
                if response.status == 405:
                    async with session.post(
                        _aria_url(),
                        headers=_aria_headers(),
                        json={**payload, 'stream': False},
                        ssl=AIOHTTP_CLIENT_SESSION_SSL,
                    ) as fallback_response:
                        text = await fallback_response.text()
                        if fallback_response.status >= 400:
                            yield _error_event(text[:500])
                            yield 'data: [DONE]\n\n'
                        else:
                            for event in _completion_events(text, 'Aria'):
                                yield event
                    return

                if response.status >= 400:
                    text = await response.text()
                    yield _error_event(text[:500])
                    yield 'data: [DONE]\n\n'
                    return

                content_type = response.headers.get('Content-Type', '')
                if 'application/json' in content_type:
                    text = await response.text()
                    for event in _completion_events(text, 'Aria'):
                        yield event
                    return

                async for line in _iter_complete_stream_lines(response.content):
                    yield line
    except (aiohttp.ClientError, TimeoutError) as exc:
        log.error('Aria agent connection error: %s', exc, exc_info=True)
        yield _error_event(str(exc))
        yield 'data: [DONE]\n\n'


def _chunk_page(chunk: dict[str, Any]) -> int | None:
    for key in ('page', 'page_number', 'page_num'):
        value = chunk.get(key)
        if isinstance(value, int):
            return max(0, value - 1 if key != 'page' and value > 0 else value)
    positions = chunk.get('positions')
    if isinstance(positions, list) and positions:
        first = positions[0]
        if isinstance(first, (list, tuple)) and first and isinstance(first[0], int):
            return max(0, first[0] - 1)
    return None


def _ragflow_citation_sources(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources = []
    for item in documents:
        source_id = f'ragflow:{item["dataset_id"]}:{item["document_id"]}'
        url = (
            f'/api/v1/ragflow/datasets/{item["dataset_id"]}'
            f'/documents/{item["document_id"]}/content'
        )
        parts = item.get('parts') or []
        sources.append(
            {
                'source': {
                    'id': source_id,
                    'name': item['name'],
                    'type': 'ragflow',
                    'url': url,
                },
                'document': [part['content'] for part in parts],
                'metadata': [
                    {
                        'source': source_id,
                        'name': item['name'],
                        'ragflow': True,
                        'ragflow_dataset_id': item['dataset_id'],
                        'ragflow_document_id': item['document_id'],
                        'dataset_name': item.get('dataset_name'),
                        'space_name': item.get('space_name'),
                        **({'page': part['page']} if part.get('page') is not None else {}),
                    }
                    for part in parts
                ],
                'distances': [part['similarity'] for part in parts],
            }
        )
    return sources


async def _stream_with_sources(stream, sources: list[dict[str, Any]]):
    if sources:
        yield f'data: {json.dumps({"sources": sources}, ensure_ascii=False)}\n\n'
    async for chunk in stream:
        yield chunk


def _json_response_with_sources(payload: dict[str, Any], sources: list[dict[str, Any]]) -> JSONResponse:
    return JSONResponse(content={**payload, **({'sources': sources} if sources else {})})


async def generate_agent_chat_completion(
    request: Request,
    form_data: dict[str, Any],
    user: Any,
    model: dict[str, Any],
):
    """Dispatch a native ЛИА completion to the selected system agent."""

    agent = model.get('agent') or {}
    if agent.get('provider') in {'aria', 'office'}:
        if not LIA_ARIA_ENABLED or not LIA_ARIA_API_BASE_URL:
            raise HTTPException(status_code=503, detail='Aria agent is not configured')
        payload = _build_aria_payload(
            form_data,
            OFFICE_AGENT_SYSTEM_PROMPT if agent.get('provider') == 'office' else None,
        )
        if payload['stream']:
            return StreamingResponse(_stream_aria(payload), media_type='text/event-stream')

        timeout = aiohttp.ClientTimeout(total=120)
        try:
            async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as session:
                async with session.post(
                    _aria_url(),
                    headers=_aria_headers(),
                    json=payload,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as response:
                    text = await response.text()
                    if response.status >= 400:
                        raise HTTPException(status_code=response.status, detail=text[:500])
                    return JSONResponse(content=json.loads(text))
        except aiohttp.ClientError as exc:
            log.error('Aria agent connection error: %s', exc, exc_info=True)
            raise HTTPException(status_code=503, detail=f'Aria connection error: {exc}') from exc

    if agent.get('provider') == 'ragflow':
        if not is_ragflow_configured():
            raise HTTPException(status_code=503, detail='RAGFlow is not configured')
        agent_id = agent.get('id')
        knowledge_agent = await get_agent(user.id, agent_id)
        try:
            knowledge_agent = await sync_agent_chat(knowledge_agent.get('owner_id') or user.id, knowledge_agent)
        except HTTPException as exc:
            # The RAGFlow chat object is kept in sync for compatibility with its
            # UI, but retrieval below only needs the selected datasets.
            log.warning('Unable to sync RAGFlow chat for agent %s: %s', agent_id, exc.detail)
        dataset_ids = knowledge_agent.get('dataset_ids') or []
        if not dataset_ids:
            raise HTTPException(
                status_code=400,
                detail='У ассистента нет баз знаний. Добавьте базу в подключённое пространство.',
            )

        messages = _prepare_messages(form_data.get('messages') or [])
        question = next(
            (str(item.get('content') or '') for item in reversed(messages) if item.get('role') == 'user'),
            '',
        )
        if not question:
            raise HTTPException(status_code=400, detail='Сообщение пользователя не найдено')

        params = knowledge_agent.get('params') or {}
        chunks = await ragflow_client.search_datasets(
            question,
            dataset_ids,
            top_k=int(params.get('top_k', 30)),
            similarity_threshold=float(params.get('similarity_threshold', 0.2)),
            vector_similarity_weight=float(params.get('vector_similarity_weight', 1.0)),
        )

        # A click on "Изменить в чате" carries the exact source reference in
        # request metadata. Include its chunks even when semantic retrieval of
        # a short edit prompt would not rank the document highly enough.
        explicit_refs = (form_data.get('metadata') or {}).get('ragflow_document_refs') or []
        for ref in explicit_refs[:5]:
            dataset_id = str(ref.get('dataset_id') or '')
            document_id = str(ref.get('document_id') or '')
            if dataset_id not in dataset_ids or not document_id:
                continue
            try:
                document = await ragflow_client.get_document(dataset_id, document_id)
                explicit_chunks = await ragflow_client.get_document_chunks(dataset_id, document_id)
            except HTTPException as exc:
                log.warning('Unable to load selected RAGFlow document %s: %s', document_id, exc.detail)
                continue
            for chunk in explicit_chunks:
                chunks.append(
                    {
                        **chunk,
                        'dataset_id': dataset_id,
                        'document_id': document_id,
                        'document_keyword': document.get('name') or ref.get('name') or 'Документ',
                        'similarity': max(float(chunk.get('similarity') or 0.0), 1.0),
                    }
                )

        spaces = await list_spaces(user.id)
        dataset_labels: dict[str, dict[str, str]] = {}
        for space in spaces:
            for dataset in space.get('datasets') or []:
                dataset_id = str(dataset.get('id') or '')
                if dataset_id:
                    dataset_labels[dataset_id] = {
                        'dataset_name': str(dataset.get('name') or 'База знаний'),
                        'space_name': str(space.get('name') or 'Пространство'),
                    }

        documents: dict[tuple[str, str], dict[str, Any]] = {}
        for chunk in chunks:
            dataset_id = str(chunk.get('dataset_id') or '')
            document_id = str(chunk.get('document_id') or '')
            if not dataset_id or not document_id:
                continue
            key = (dataset_id, document_id)
            labels = dataset_labels.get(dataset_id, {})
            item = documents.setdefault(
                key,
                {
                    'dataset_id': dataset_id,
                    'document_id': document_id,
                    'name': chunk.get('document_keyword') or chunk.get('doc_name') or 'Документ',
                    'dataset_name': labels.get('dataset_name') or 'База знаний',
                    'space_name': labels.get('space_name') or 'Пространство',
                    'similarity': 0.0,
                    'parts': [],
                },
            )
            content = chunk.get('content') or chunk.get('text')
            if content:
                similarity = float(chunk.get('similarity') or 0.0)
                normalized_content = str(content)
                if not any(part['content'] == normalized_content for part in item['parts']):
                    item['parts'].append(
                        {
                            'content': normalized_content,
                            'similarity': similarity,
                            'page': _chunk_page(chunk),
                        }
                    )
                item['similarity'] = max(float(item['similarity']), similarity)

        sorted_documents = sorted(documents.values(), key=lambda value: value['similarity'], reverse=True)
        citation_sources = _ragflow_citation_sources(sorted_documents)
        metadata = form_data.setdefault('metadata', {})
        explicit_keys = {
            (str(ref.get('dataset_id') or ''), str(ref.get('document_id') or '')) for ref in explicit_refs
        }
        metadata['ragflow_sources'] = [
            {
                'index': index,
                'dataset_id': item['dataset_id'],
                'document_id': item['document_id'],
                'name': item['name'],
                'dataset_name': item['dataset_name'],
                'space_name': item['space_name'],
                'selected': (item['dataset_id'], item['document_id']) in explicit_keys,
            }
            for index, item in enumerate(sorted_documents, start=1)
        ]
        if citation_sources:
            metadata['sources'] = citation_sources

        context_parts = []
        for index, item in enumerate(sorted_documents, start=1):
            source_location = (
                f'пространство «{item["space_name"]}», база «{item["dataset_name"]}», '
                f'dataset_id={item["dataset_id"]}, document_id={item["document_id"]}'
            )
            context_parts.append(
                f'[{index}] Документ «{item["name"]}» ({source_location}):\n'
                + '\n\n'.join(part['content'] for part in item['parts'])
            )
        context = '\n\n'.join(context_parts)
        base_prompt = knowledge_agent.get('prompt') or 'Отвечай по подключённым базам знаний.'
        system_prompt = (
            f'{base_prompt}\n\n'
            'Используй приведённые фрагменты как основной источник. '
            'Не выдумывай отсутствующие сведения. Для фактов указывай номера источников [1], [2].\n\n'
            f'{RAGFLOW_OFFICE_SYSTEM_PROMPT if LIA_OFFICE_ENABLED else ""}\n\n'
            f'Контекст из баз знаний:\n{context or "Релевантные фрагменты не найдены."}'
        )
        prepared_messages = [item for item in messages if item.get('role') != 'system']
        prepared_messages.insert(0, {'role': 'system', 'content': system_prompt})

        generation_param_names = {
            'max_tokens',
            'temperature',
            'top_p',
            'frequency_penalty',
            'presence_penalty',
            'seed',
            'stop',
        }
        generation_params = {
            key: value for key, value in params.items() if key in generation_param_names and value is not None
        }
        target_model = str(knowledge_agent.get('model') or '').strip()
        if not target_model:
            if not LIA_ARIA_ENABLED or not LIA_ARIA_API_BASE_URL:
                raise HTTPException(
                    status_code=503,
                    detail='Системная модель Ария не настроена для ассистентов по базам знаний',
                )
            aria_form = {
                **form_data,
                'messages': prepared_messages,
                'params': {**(form_data.get('params') or {}), **generation_params},
            }
            payload = _build_aria_payload(aria_form)
            if payload['stream']:
                return StreamingResponse(
                    _stream_with_sources(_stream_aria(payload), citation_sources),
                    media_type='text/event-stream',
                )

            timeout = aiohttp.ClientTimeout(total=120)
            try:
                async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as session:
                    async with session.post(
                        _aria_url(),
                        headers=_aria_headers(),
                        json=payload,
                        ssl=AIOHTTP_CLIENT_SESSION_SSL,
                    ) as response:
                        text = await response.text()
                        if response.status >= 400:
                            raise HTTPException(status_code=response.status, detail=text[:500])
                        return _json_response_with_sources(json.loads(text), citation_sources)
            except aiohttp.ClientError as exc:
                log.error('Knowledge agent default Aria connection error: %s', exc, exc_info=True)
                raise HTTPException(status_code=503, detail=f'Aria connection error: {exc}') from exc

        if target_model.startswith(('agent:ragflow:', 'agent:sip:', 'agent:aria', 'agent:office')):
            raise HTTPException(status_code=400, detail='Для ассистента выбрана некорректная LLM')

        delegated_form = {
            **form_data,
            'model': target_model,
            'messages': prepared_messages,
            'params': {**(form_data.get('params') or {}), **generation_params},
        }
        # Local import avoids an import cycle while delegating generation to the
        # native Open WebUI provider selected for this knowledge agent.
        from open_webui.utils.chat import generate_chat_completion

        response = await generate_chat_completion(
            request=request,
            form_data=delegated_form,
            user=user,
            bypass_filter=False,
            bypass_system_prompt=True,
        )
        if form_data.get('stream') and isinstance(response, StreamingResponse):
            return StreamingResponse(
                _stream_with_sources(response.body_iterator, citation_sources),
                media_type='text/event-stream',
                background=response.background,
            )
        if isinstance(response, JSONResponse):
            try:
                response_payload = json.loads(response.body.decode('utf-8', 'replace'))
            except (AttributeError, json.JSONDecodeError):
                return response
            return _json_response_with_sources(response_payload, citation_sources)
        if isinstance(response, dict):
            return {**response, **({'sources': citation_sources} if citation_sources else {})}
        return response

    if agent.get('provider') != 'sip':
        raise HTTPException(status_code=400, detail='Unsupported agent provider')
    if not LIA_LND_ENABLED or not LIA_LND_API_BASE_URL:
        raise HTTPException(status_code=503, detail='SIP agent is not configured')

    mode = _sip_mode(form_data.get('model', ''))
    payload = _build_payload(form_data, mode)

    if payload['stream']:
        return StreamingResponse(_stream_sip(payload), media_type='text/event-stream')

    timeout = aiohttp.ClientTimeout(total=120)
    try:
        async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as session:
            async with session.post(
                _lnd_url(),
                headers=_headers(),
                json=payload,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as response:
                text = await response.text()
                if response.status >= 400:
                    raise HTTPException(status_code=response.status, detail=text[:500])
                return JSONResponse(content=json.loads(text))
    except aiohttp.ClientError as exc:
        log.error('SIP agent connection error: %s', exc, exc_info=True)
        raise HTTPException(status_code=503, detail=f'SIP connection error: {exc}') from exc
