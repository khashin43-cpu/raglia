"""Authenticated LIA API for knowledge agents backed by RAGFlow 0.24."""

from __future__ import annotations

import mimetypes
import time
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from open_webui.internal.ragflow_client import is_ragflow_configured, ragflow_base_url, ragflow_client
from open_webui.internal.ragflow_knowledge import (
    add_space_member,
    agent_records_for_space,
    find_dataset,
    get_agent,
    get_owned_agent,
    get_space,
    list_agents,
    list_invitations,
    list_owned_agents,
    list_space_memberships,
    list_spaces,
    new_id,
    remove_space_member,
    require_space_owner,
    save_agents,
    save_invitations,
    save_space,
    save_space_memberships,
    save_spaces,
    sync_agent_chat,
)
from open_webui.models.users import Users
from open_webui.utils.auth import get_verified_user
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter()


class SpaceCreateForm(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default='', max_length=1000)
    model_config = ConfigDict(extra='forbid')


class SpaceUpdateForm(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    model_config = ConfigDict(extra='forbid')


class DatasetCreateForm(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    chunk_method: str = Field(default='naive', min_length=1, max_length=64)
    model_config = ConfigDict(extra='forbid')


class DatasetUpdateForm(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    model_config = ConfigDict(extra='forbid')


class AgentForm(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default='', max_length=2000)
    prompt: str = Field(default='', max_length=20000)
    model: str = Field(default='', max_length=512)
    space_ids: list[str] = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    active: bool = True
    model_config = ConfigDict(extra='forbid')


class SpaceMembersInviteForm(BaseModel):
    user_ids: list[str] = Field(min_length=1, max_length=100)
    model_config = ConfigDict(extra='forbid')


class SpaceInvitationResponseForm(BaseModel):
    accept: bool
    model_config = ConfigDict(extra='forbid')


async def _sync_agents_for_space(space_id: str) -> None:
    for owner_id, agent in await agent_records_for_space(space_id):
        try:
            await sync_agent_chat(owner_id, agent)
        except HTTPException:
            # The hierarchy update remains valid even if RAGFlow is temporarily unavailable.
            pass


async def _refresh_dataset_count(user_id: str, dataset_id: str) -> int:
    space, _ = await find_dataset(user_id, dataset_id)
    documents = await ragflow_client.list_documents(dataset_id)
    count = len(documents)
    for dataset in space.get('datasets') or []:
        if dataset.get('id') == dataset_id:
            dataset['doc_count'] = count
            dataset['updated_at'] = int(time.time())
    await save_space(space)
    return count


@router.get('/status')
async def get_ragflow_status(user=Depends(get_verified_user)):
    del user
    configured = is_ragflow_configured()
    connected = False
    error = None
    if configured:
        try:
            await ragflow_client.check_connection()
            connected = True
        except HTTPException as exc:
            error = str(exc.detail)
    return {
        'configured': configured,
        'connected': connected,
        'url': ragflow_base_url() if configured else None,
        'version': '0.24',
        'mode': 'knowledge-agents',
        'error': error,
    }


@router.get('/spaces')
async def get_spaces(user=Depends(get_verified_user)):
    return await list_spaces(user.id)


@router.post('/spaces')
async def create_space(form: SpaceCreateForm, user=Depends(get_verified_user)):
    now = int(time.time())
    space = {
        'id': new_id(),
        'owner_id': user.id,
        'name': form.name.strip(),
        'description': form.description.strip(),
        'datasets': [],
        'members': [{'user_id': user.id, 'role': 'owner', 'joined_at': now}],
        'created_at': now,
        'updated_at': now,
    }
    spaces = [item for item in await list_spaces(user.id) if item.get('owner_id') == user.id]
    spaces.append(space)
    await save_spaces(user.id, spaces)
    return {**space, 'role': 'owner', 'can_manage': True, 'is_shared': False, 'member_count': 1}


@router.put('/spaces/{space_id}')
async def update_space(space_id: str, form: SpaceUpdateForm, user=Depends(get_verified_user)):
    space = await require_space_owner(user.id, space_id)
    updates = form.model_dump(exclude_unset=True)
    if 'name' in updates:
        updates['name'] = updates['name'].strip()
    if 'description' in updates and updates['description'] is not None:
        updates['description'] = updates['description'].strip()
    updated = {**space, **updates, 'updated_at': int(time.time())}
    await save_space(updated)
    return updated


@router.delete('/spaces/{space_id}')
async def delete_space(space_id: str, user=Depends(get_verified_user)):
    space = await require_space_owner(user.id, space_id)
    for dataset in space.get('datasets') or []:
        try:
            await ragflow_client.delete_dataset(dataset['id'])
        except HTTPException:
            pass
    spaces = [
        item for item in await list_spaces(user.id) if item.get('owner_id') == user.id and item.get('id') != space_id
    ]
    await save_spaces(user.id, spaces)
    for member in space.get('members') or []:
        member_id = member.get('user_id')
        if member_id and member_id != user.id:
            memberships = [
                membership
                for membership in await list_space_memberships(member_id)
                if membership.get('owner_id') != user.id or membership.get('space_id') != space_id
            ]
            await save_space_memberships(member_id, memberships)
    for owner_id, agent in await agent_records_for_space(space_id):
        owner_agents = await list_owned_agents(owner_id)
        updated_agent = next((item for item in owner_agents if item.get('id') == agent.get('id')), None)
        if not updated_agent:
            continue
        updated_agent['space_ids'] = [item for item in updated_agent.get('space_ids') or [] if item != space_id]
        await save_agents(owner_id, owner_agents)
        if updated_agent.get('ragflow_chat_id') and updated_agent.get('space_ids'):
            try:
                await sync_agent_chat(owner_id, updated_agent)
            except HTTPException:
                pass
    return {'success': True}


@router.get('/spaces/{space_id}/members')
async def get_space_members(space_id: str, user=Depends(get_verified_user)):
    space = await get_space(user.id, space_id)
    result = []
    for member in space.get('members') or []:
        member_id = member.get('user_id')
        account = await Users.get_user_by_id(member_id) if member_id else None
        result.append(
            {
                **member,
                'name': account.name if account else 'Пользователь',
                'email': account.email if account else '',
                'profile_image_url': account.profile_image_url if account else None,
            }
        )
    return result


@router.post('/spaces/{space_id}/member-invitations')
async def invite_space_members(
    space_id: str,
    form: SpaceMembersInviteForm,
    user=Depends(get_verified_user),
):
    space = await require_space_owner(user.id, space_id)
    existing_ids = {member.get('user_id') for member in space.get('members') or []}
    invited_ids: list[str] = []
    already_member_ids: list[str] = []
    for invited_user_id in dict.fromkeys(item.strip() for item in form.user_ids if item.strip()):
        if invited_user_id in existing_ids:
            already_member_ids.append(invited_user_id)
            continue
        invited_user = await Users.get_user_by_id(invited_user_id)
        if not invited_user:
            raise HTTPException(status_code=404, detail='Один или несколько пользователей не найдены')
        invitations = await list_invitations(invited_user_id)
        invitation = next(
            (item for item in invitations if item.get('space_id') == space_id and item.get('owner_id') == user.id),
            None,
        )
        payload = {
            'id': invitation.get('id') if invitation else new_id(),
            'space_id': space_id,
            'space_name': space.get('name'),
            'owner_id': user.id,
            'invited_user_id': invited_user_id,
            'invited_by': user.id,
            'status': 'pending',
            'created_at': int(time.time()),
        }
        if invitation:
            invitations = [payload if item.get('id') == invitation.get('id') else item for item in invitations]
        else:
            invitations.append(payload)
        await save_invitations(invited_user_id, invitations)
        invited_ids.append(invited_user_id)
    return {'space_id': space_id, 'invited_user_ids': invited_ids, 'existing_user_ids': already_member_ids}


@router.delete('/spaces/{space_id}/members/{member_id}')
async def delete_space_member(space_id: str, member_id: str, user=Depends(get_verified_user)):
    await require_space_owner(user.id, space_id)
    await remove_space_member(user.id, space_id, member_id)
    return {'success': True}


@router.get('/space-invitations/pending')
async def get_pending_space_invitations(user=Depends(get_verified_user)):
    result = []
    for invitation in await list_invitations(user.id):
        if invitation.get('status') != 'pending':
            continue
        owner_space = next(
            (
                space
                for space in await list_spaces(invitation.get('owner_id'))
                if space.get('id') == invitation.get('space_id') and space.get('owner_id') == invitation.get('owner_id')
            ),
            None,
        )
        if not owner_space:
            continue
        inviter = await Users.get_user_by_id(invitation.get('invited_by'))
        result.append(
            {
                **invitation,
                'space_name': owner_space.get('name'),
                'inviter_name': (inviter.name or inviter.email) if inviter else 'Пользователь',
            }
        )
    return result


@router.post('/space-invitations/{invitation_id}/respond')
async def respond_to_space_invitation(
    invitation_id: str,
    form: SpaceInvitationResponseForm,
    user=Depends(get_verified_user),
):
    invitations = await list_invitations(user.id)
    invitation = next(
        (item for item in invitations if item.get('id') == invitation_id and item.get('status') == 'pending'),
        None,
    )
    if not invitation:
        raise HTTPException(status_code=404, detail='Приглашение не найдено или уже обработано')
    if form.accept:
        await add_space_member(invitation['owner_id'], invitation['space_id'], user.id)
    invitation = {
        **invitation,
        'status': 'accepted' if form.accept else 'declined',
        'responded_at': int(time.time()),
    }
    await save_invitations(
        user.id,
        [invitation if item.get('id') == invitation_id else item for item in invitations],
    )
    return {
        'accepted': form.accept,
        'space_id': invitation['space_id'],
        'space_name': invitation.get('space_name'),
    }


@router.post('/spaces/{space_id}/datasets')
async def create_dataset(space_id: str, form: DatasetCreateForm, user=Depends(get_verified_user)):
    space = await get_space(user.id, space_id)
    result = await ragflow_client.create_dataset(form.name.strip(), form.chunk_method)
    dataset_id = result.get('id')
    if not dataset_id:
        raise HTTPException(status_code=502, detail='RAGFlow did not return a dataset ID')
    dataset = {
        'id': dataset_id,
        'name': result.get('name') or form.name.strip(),
        'chunk_method': result.get('chunk_method') or form.chunk_method,
        'doc_count': 0,
        'created_at': int(time.time()),
    }
    space.setdefault('datasets', []).append(dataset)
    space['updated_at'] = int(time.time())
    await save_space(space)
    await _sync_agents_for_space(space_id)
    return dataset


@router.put('/datasets/{dataset_id}')
async def update_dataset(dataset_id: str, form: DatasetUpdateForm, user=Depends(get_verified_user)):
    space, _ = await find_dataset(user.id, dataset_id)
    name = form.name.strip()
    await ragflow_client.update_dataset(dataset_id, {'name': name})
    for dataset in space.get('datasets') or []:
        if dataset.get('id') == dataset_id:
            dataset['name'] = name
            dataset['updated_at'] = int(time.time())
    await save_space(space)
    return {'id': dataset_id, 'name': name, 'space_id': space['id']}


@router.delete('/datasets/{dataset_id}')
async def delete_dataset(dataset_id: str, user=Depends(get_verified_user)):
    space, _ = await find_dataset(user.id, dataset_id)
    await ragflow_client.delete_dataset(dataset_id)
    space['datasets'] = [dataset for dataset in space.get('datasets') or [] if dataset.get('id') != dataset_id]
    space['updated_at'] = int(time.time())
    await save_space(space)
    await _sync_agents_for_space(space['id'])
    return {'success': True}


@router.get('/datasets/{dataset_id}/documents')
async def get_documents(dataset_id: str, user=Depends(get_verified_user)):
    await find_dataset(user.id, dataset_id)
    documents = await ragflow_client.list_documents(dataset_id)
    await _refresh_dataset_count(user.id, dataset_id)
    return documents


@router.post('/datasets/{dataset_id}/documents')
async def upload_documents(
    dataset_id: str,
    files: list[UploadFile] = File(...),
    user=Depends(get_verified_user),
):
    await find_dataset(user.id, dataset_id)
    uploaded: list[dict[str, Any]] = []
    document_ids: list[str] = []
    for file in files:
        result = await ragflow_client.upload_document(dataset_id, file)
        uploaded.extend(result)
        document_ids.extend(item['id'] for item in result if item.get('id'))
    if document_ids:
        await ragflow_client.parse_documents(dataset_id, document_ids)
    await _refresh_dataset_count(user.id, dataset_id)
    return {'documents': uploaded, 'parsing_started': document_ids}


@router.delete('/datasets/{dataset_id}/documents/{document_id}')
async def delete_document(dataset_id: str, document_id: str, user=Depends(get_verified_user)):
    await find_dataset(user.id, dataset_id)
    await ragflow_client.delete_document(dataset_id, document_id)
    await _refresh_dataset_count(user.id, dataset_id)
    return {'success': True}


@router.get('/datasets/{dataset_id}/documents/{document_id}/chunks')
async def get_document_chunks(dataset_id: str, document_id: str, user=Depends(get_verified_user)):
    await find_dataset(user.id, dataset_id)
    return await ragflow_client.get_document_chunks(dataset_id, document_id)


@router.get('/datasets/{dataset_id}/documents/{document_id}/content')
async def get_document_content(dataset_id: str, document_id: str, user=Depends(get_verified_user)):
    """Proxy an original RAGFlow document after checking LIA space access."""

    await find_dataset(user.id, dataset_id)
    document = await ragflow_client.get_document(dataset_id, document_id)
    content, upstream_content_type = await ragflow_client.download_document(dataset_id, document_id)
    filename = str(document.get('name') or f'{document_id}.bin').replace('\r', '_').replace('\n', '_')
    content_type = upstream_content_type or mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    disposition = f"inline; filename*=UTF-8''{quote(filename, safe='')}"
    return Response(
        content=content,
        media_type=content_type,
        headers={
            'Content-Disposition': disposition,
            'Cache-Control': 'private, max-age=60',
            'X-Content-Type-Options': 'nosniff',
        },
    )


@router.get('/agents')
async def get_agents(user=Depends(get_verified_user)):
    return await list_agents(user.id)


@router.get('/agents/{agent_id}')
async def get_agent_by_id(agent_id: str, user=Depends(get_verified_user)):
    return await get_agent(user.id, agent_id)


@router.post('/agents')
async def create_agent(form: AgentForm, user=Depends(get_verified_user)):
    known_space_ids = {space['id'] for space in await list_spaces(user.id)}
    if any(space_id not in known_space_ids for space_id in form.space_ids):
        raise HTTPException(status_code=400, detail='Выбрано неизвестное пространство')
    now = int(time.time())
    agent = {
        'id': new_id(),
        'owner_id': user.id,
        **form.model_dump(),
        'name': form.name.strip(),
        'description': form.description.strip(),
        'prompt': form.prompt.strip(),
        'ragflow_chat_id': None,
        'created_at': now,
        'updated_at': now,
    }
    agents = await list_owned_agents(user.id)
    agents.append(agent)
    await save_agents(user.id, agents)
    try:
        agent = await sync_agent_chat(user.id, agent)
    except HTTPException:
        # Empty spaces are valid; the chat assistant will be created after a dataset is added.
        pass
    return agent


@router.put('/agents/{agent_id}')
async def update_agent(agent_id: str, form: AgentForm, user=Depends(get_verified_user)):
    existing = await get_owned_agent(user.id, agent_id)
    known_space_ids = {space['id'] for space in await list_spaces(user.id)}
    if any(space_id not in known_space_ids for space_id in form.space_ids):
        raise HTTPException(status_code=400, detail='Выбрано неизвестное пространство')
    updated = {
        **existing,
        **form.model_dump(),
        'name': form.name.strip(),
        'description': form.description.strip(),
        'prompt': form.prompt.strip(),
        'updated_at': int(time.time()),
    }
    agents = [updated if item.get('id') == agent_id else item for item in await list_owned_agents(user.id)]
    await save_agents(user.id, agents)
    try:
        return await sync_agent_chat(user.id, updated)
    except HTTPException:
        # Editing the LIA agent remains possible while RAGFlow is temporarily unavailable.
        return updated


@router.delete('/agents/{agent_id}')
async def delete_agent(agent_id: str, user=Depends(get_verified_user)):
    agent = await get_owned_agent(user.id, agent_id)
    if agent.get('ragflow_chat_id'):
        try:
            await ragflow_client.delete_chat(agent['ragflow_chat_id'])
        except HTTPException:
            pass
    await save_agents(user.id, [item for item in await list_owned_agents(user.id) if item.get('id') != agent_id])
    return {'success': True}
