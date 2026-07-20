import asyncio

from open_webui.internal import ragflow_knowledge as knowledge


def test_space_membership_shares_only_safe_agents(monkeypatch):
    store = {}

    async def fake_get(key, default=None):
        return store.get(key, default)

    async def fake_upsert(values):
        store.update(values)

    async def fake_get_namespace(namespace):
        return {key: value for key, value in store.items() if key.startswith(f'{namespace}.')}

    monkeypatch.setattr(knowledge.Config, 'get', staticmethod(fake_get))
    monkeypatch.setattr(knowledge.Config, 'upsert', staticmethod(fake_upsert))
    monkeypatch.setattr(knowledge.Config, 'get_namespace', staticmethod(fake_get_namespace))

    async def scenario():
        owner_id = 'owner'
        member_id = 'member'
        owner_member = {'user_id': owner_id, 'role': 'owner', 'joined_at': 1}
        shared_space = {
            'id': 'shared',
            'owner_id': owner_id,
            'name': 'Общее',
            'datasets': [{'id': 'shared-dataset'}],
            'members': [owner_member],
            'created_at': 1,
        }
        private_space = {
            'id': 'private',
            'owner_id': owner_id,
            'name': 'Личное',
            'datasets': [{'id': 'private-dataset'}],
            'members': [owner_member],
            'created_at': 1,
        }
        await knowledge.save_spaces(owner_id, [shared_space, private_space])
        await knowledge.add_space_member(owner_id, shared_space['id'], member_id)

        member_spaces = await knowledge.list_spaces(member_id)
        assert [space['id'] for space in member_spaces] == ['shared']
        assert member_spaces[0]['role'] == 'member'

        await knowledge.save_agents(
            owner_id,
            [
                {'id': 'visible', 'owner_id': owner_id, 'space_ids': ['shared'], 'name': 'Общий'},
                {
                    'id': 'hidden',
                    'owner_id': owner_id,
                    'space_ids': ['shared', 'private'],
                    'name': 'Смешанный',
                },
            ],
        )
        member_agents = await knowledge.list_agents(member_id)
        assert [agent['id'] for agent in member_agents] == ['visible']
        assert member_agents[0]['shared'] is True
        assert member_agents[0]['can_edit'] is False

        await knowledge.save_agents(
            member_id,
            [{'id': 'member-agent', 'owner_id': member_id, 'space_ids': ['shared'], 'name': 'Командный'}],
        )
        assert any(agent['id'] == 'member-agent' for agent in await knowledge.list_agents(owner_id))

        await knowledge.remove_space_member(owner_id, shared_space['id'], member_id)
        assert await knowledge.list_spaces(member_id) == []
        remaining_member_agents = await knowledge.list_agents(member_id)
        assert len(remaining_member_agents) == 1
        assert remaining_member_agents[0]['space_ids'] == []
        assert not any(agent['id'] == 'member-agent' for agent in await knowledge.list_agents(owner_id))

    asyncio.run(scenario())
