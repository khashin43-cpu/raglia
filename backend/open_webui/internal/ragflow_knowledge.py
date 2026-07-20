"""Persistent LIA hierarchy and sharing for RAGFlow knowledge assistants."""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from open_webui.internal.ragflow_client import ragflow_client
from open_webui.models.config import Config

_SPACES_NAMESPACE = 'lia.ragflow.spaces'
_AGENTS_NAMESPACE = 'lia.ragflow.knowledge_agents'
_MEMBERSHIPS_NAMESPACE = 'lia.ragflow.space_memberships'
_INVITATIONS_NAMESPACE = 'lia.ragflow.space_invitations'


def _spaces_key(user_id: str) -> str:
    return f'{_SPACES_NAMESPACE}.{user_id}'


def _agents_key(user_id: str) -> str:
    return f'{_AGENTS_NAMESPACE}.{user_id}'


def _memberships_key(user_id: str) -> str:
    return f'{_MEMBERSHIPS_NAMESPACE}.{user_id}'


def _invitations_key(user_id: str) -> str:
    return f'{_INVITATIONS_NAMESPACE}.{user_id}'


def _owner_from_key(key: str, namespace: str) -> str:
    return key.removeprefix(f'{namespace}.')


def _normalize_space(space: dict[str, Any], owner_id: str, viewer_id: str | None = None) -> dict[str, Any]:
    normalized = {**space, 'owner_id': space.get('owner_id') or owner_id}
    members = [member for member in normalized.get('members') or [] if member.get('user_id')]
    if not any(member.get('user_id') == owner_id for member in members):
        members.insert(0, {'user_id': owner_id, 'role': 'owner', 'joined_at': normalized.get('created_at')})
    normalized['members'] = members
    if viewer_id is not None:
        role = (
            'owner'
            if viewer_id == owner_id
            else next(
                (member.get('role') or 'member' for member in members if member.get('user_id') == viewer_id),
                None,
            )
        )
        normalized['role'] = role
        normalized['can_manage'] = role == 'owner'
        normalized['is_shared'] = role != 'owner' or len(members) > 1
        normalized['member_count'] = len(members)
    return normalized


async def list_owned_spaces(owner_id: str) -> list[dict[str, Any]]:
    value = await Config.get(_spaces_key(owner_id), [])
    spaces = value if isinstance(value, list) else []
    return [_normalize_space(space, owner_id) for space in spaces]


async def list_space_memberships(user_id: str) -> list[dict[str, str]]:
    value = await Config.get(_memberships_key(user_id), [])
    return value if isinstance(value, list) else []


async def save_space_memberships(user_id: str, memberships: list[dict[str, str]]) -> None:
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for membership in memberships:
        owner_id = membership.get('owner_id')
        space_id = membership.get('space_id')
        if owner_id and space_id:
            unique[(owner_id, space_id)] = {'owner_id': owner_id, 'space_id': space_id}
    await Config.upsert({_memberships_key(user_id): list(unique.values())})


async def list_spaces(user_id: str) -> list[dict[str, Any]]:
    result = [_normalize_space(space, user_id, user_id) for space in await list_owned_spaces(user_id)]
    memberships = await list_space_memberships(user_id)
    owner_ids = {membership['owner_id'] for membership in memberships if membership.get('owner_id')}
    owner_spaces = {owner_id: await list_owned_spaces(owner_id) for owner_id in owner_ids if owner_id != user_id}
    valid_memberships: list[dict[str, str]] = []
    known_ids = {space['id'] for space in result}
    for membership in memberships:
        owner_id = membership.get('owner_id')
        space_id = membership.get('space_id')
        if not owner_id or not space_id or owner_id == user_id:
            continue
        space = next((item for item in owner_spaces.get(owner_id, []) if item.get('id') == space_id), None)
        if not space:
            continue
        normalized = _normalize_space(space, owner_id, user_id)
        if not normalized.get('role') or normalized['id'] in known_ids:
            continue
        valid_memberships.append({'owner_id': owner_id, 'space_id': space_id})
        known_ids.add(normalized['id'])
        result.append(normalized)
    if valid_memberships != memberships:
        await save_space_memberships(user_id, valid_memberships)
    return sorted(result, key=lambda item: item.get('updated_at') or item.get('created_at') or 0, reverse=True)


async def save_spaces(owner_id: str, spaces: list[dict[str, Any]]) -> None:
    owned_spaces = []
    for space in spaces:
        space_owner_id = space.get('owner_id') or owner_id
        if space_owner_id != owner_id:
            continue
        stored = _normalize_space(space, owner_id)
        for field in ('role', 'can_manage', 'is_shared', 'member_count'):
            stored.pop(field, None)
        owned_spaces.append(stored)
    await Config.upsert({_spaces_key(owner_id): owned_spaces})


async def save_space(space: dict[str, Any]) -> dict[str, Any]:
    owner_id = space.get('owner_id')
    if not owner_id:
        raise HTTPException(status_code=500, detail='У пространства не определён владелец')
    spaces = await list_owned_spaces(owner_id)
    updated = False
    for index, existing in enumerate(spaces):
        if existing.get('id') == space.get('id'):
            spaces[index] = _normalize_space(space, owner_id)
            updated = True
            break
    if not updated:
        spaces.append(_normalize_space(space, owner_id))
    await save_spaces(owner_id, spaces)
    return _normalize_space(space, owner_id)


async def get_space(user_id: str, space_id: str) -> dict[str, Any]:
    for space in await list_spaces(user_id):
        if space.get('id') == space_id:
            return space
    raise HTTPException(status_code=404, detail='Пространство не найдено')


async def get_owned_space(owner_id: str, space_id: str) -> dict[str, Any]:
    for space in await list_owned_spaces(owner_id):
        if space.get('id') == space_id:
            return space
    raise HTTPException(status_code=404, detail='Пространство не найдено')


async def require_space_owner(user_id: str, space_id: str) -> dict[str, Any]:
    space = await get_space(user_id, space_id)
    if space.get('owner_id') != user_id:
        raise HTTPException(status_code=403, detail='Только владелец может управлять пространством')
    return space


async def add_space_member(owner_id: str, space_id: str, user_id: str) -> dict[str, Any]:
    space = await get_owned_space(owner_id, space_id)
    members = space.get('members') or []
    if not any(member.get('user_id') == user_id for member in members):
        members.append({'user_id': user_id, 'role': 'member', 'joined_at': int(time.time())})
        space = {**space, 'members': members, 'updated_at': int(time.time())}
        await save_space(space)
    memberships = await list_space_memberships(user_id)
    memberships.append({'owner_id': owner_id, 'space_id': space_id})
    await save_space_memberships(user_id, memberships)
    return space


async def remove_space_member(owner_id: str, space_id: str, user_id: str) -> None:
    if user_id == owner_id:
        raise HTTPException(status_code=400, detail='Нельзя удалить владельца пространства')
    space = await get_owned_space(owner_id, space_id)
    space['members'] = [member for member in space.get('members') or [] if member.get('user_id') != user_id]
    space['updated_at'] = int(time.time())
    await save_space(space)
    memberships = [
        membership
        for membership in await list_space_memberships(user_id)
        if membership.get('owner_id') != owner_id or membership.get('space_id') != space_id
    ]
    await save_space_memberships(user_id, memberships)

    member_agents = await list_owned_agents(user_id)
    for index, agent in enumerate(member_agents):
        if space_id not in (agent.get('space_ids') or []):
            continue
        agent['space_ids'] = [item for item in agent.get('space_ids') or [] if item != space_id]
        try:
            member_agents[index] = await sync_agent_chat(user_id, agent)
        except HTTPException:
            # Access is already revoked locally even when RAGFlow is unavailable.
            agent['dataset_ids'] = []
    await save_agents(user_id, member_agents)


async def list_invitations(user_id: str) -> list[dict[str, Any]]:
    value = await Config.get(_invitations_key(user_id), [])
    return value if isinstance(value, list) else []


async def save_invitations(user_id: str, invitations: list[dict[str, Any]]) -> None:
    await Config.upsert({_invitations_key(user_id): invitations})


async def list_owned_agents(owner_id: str) -> list[dict[str, Any]]:
    value = await Config.get(_agents_key(owner_id), [])
    agents = value if isinstance(value, list) else []
    return [{**agent, 'owner_id': agent.get('owner_id') or owner_id} for agent in agents]


async def list_agents(user_id: str) -> list[dict[str, Any]]:
    spaces = await list_spaces(user_id)
    accessible_space_ids = {space['id'] for space in spaces}
    namespace = await Config.get_namespace(_AGENTS_NAMESPACE)
    result: list[dict[str, Any]] = []
    for key, value in namespace.items():
        owner_id = _owner_from_key(key, _AGENTS_NAMESPACE)
        if not isinstance(value, list):
            continue
        for raw_agent in value:
            agent = {**raw_agent, 'owner_id': raw_agent.get('owner_id') or owner_id}
            agent_space_ids = set(agent.get('space_ids') or [])
            owned = owner_id == user_id
            # An assistant is shared only when every attached space is available to the viewer.
            if not owned and (not agent_space_ids or not agent_space_ids.issubset(accessible_space_ids)):
                continue
            agent['can_edit'] = owned
            agent['shared'] = not owned
            result.append(agent)
    return sorted(result, key=lambda item: item.get('updated_at') or item.get('created_at') or 0, reverse=True)


async def save_agents(owner_id: str, agents: list[dict[str, Any]]) -> None:
    owned_agents = []
    for agent in agents:
        agent_owner_id = agent.get('owner_id') or owner_id
        if agent_owner_id != owner_id:
            continue
        stored = {**agent, 'owner_id': owner_id}
        stored.pop('can_edit', None)
        stored.pop('shared', None)
        owned_agents.append(stored)
    await Config.upsert({_agents_key(owner_id): owned_agents})


async def get_agent(user_id: str, agent_id: str) -> dict[str, Any]:
    for agent in await list_agents(user_id):
        if agent.get('id') == agent_id:
            return agent
    raise HTTPException(status_code=404, detail='Ассистент не найден')


async def get_owned_agent(owner_id: str, agent_id: str) -> dict[str, Any]:
    for agent in await list_owned_agents(owner_id):
        if agent.get('id') == agent_id:
            return agent
    raise HTTPException(status_code=404, detail='Ассистент не найден')


async def dataset_ids_for_spaces(user_id: str, space_ids: list[str]) -> list[str]:
    selected = set(space_ids)
    result: list[str] = []
    for space in await list_spaces(user_id):
        if space.get('id') not in selected:
            continue
        for dataset in space.get('datasets') or []:
            dataset_id = dataset.get('id')
            if dataset_id and dataset_id not in result:
                result.append(dataset_id)
    return result


async def find_dataset(user_id: str, dataset_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for space in await list_spaces(user_id):
        for dataset in space.get('datasets') or []:
            if dataset.get('id') == dataset_id:
                return space, dataset
    raise HTTPException(status_code=404, detail='База знаний не найдена')


async def agent_records_for_space(space_id: str) -> list[tuple[str, dict[str, Any]]]:
    namespace = await Config.get_namespace(_AGENTS_NAMESPACE)
    result: list[tuple[str, dict[str, Any]]] = []
    for key, value in namespace.items():
        owner_id = _owner_from_key(key, _AGENTS_NAMESPACE)
        if not isinstance(value, list):
            continue
        result.extend(
            (owner_id, {**agent, 'owner_id': agent.get('owner_id') or owner_id})
            for agent in value
            if space_id in (agent.get('space_ids') or [])
        )
    return result


async def sync_agent_chat(owner_id: str, agent: dict[str, Any]) -> dict[str, Any]:
    """Synchronize an owned LIA assistant with its RAGFlow chat assistant."""

    dataset_ids = await dataset_ids_for_spaces(owner_id, agent.get('space_ids') or [])
    agent = {**agent, 'owner_id': owner_id, 'dataset_ids': dataset_ids, 'updated_at': int(time.time())}
    agents = await list_owned_agents(owner_id)
    agents = [agent if item.get('id') == agent.get('id') else item for item in agents]
    await save_agents(owner_id, agents)

    chat_id = agent.get('ragflow_chat_id')
    ragflow_name = agent.get('ragflow_name') or f'lia-{agent["id"]}'
    if dataset_ids and not chat_id:
        result = await ragflow_client.create_chat(ragflow_name, dataset_ids)
        chat_id = result.get('id') or ragflow_name
        agent = {**agent, 'ragflow_chat_id': chat_id, 'ragflow_name': ragflow_name}
    elif chat_id and dataset_ids:
        await ragflow_client.update_chat(chat_id, {'dataset_ids': dataset_ids})

    agents = await list_owned_agents(owner_id)
    agents = [agent if item.get('id') == agent.get('id') else item for item in agents]
    await save_agents(owner_id, agents)
    return agent


def new_id() -> str:
    return str(uuid4())
