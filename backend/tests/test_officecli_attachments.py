import asyncio
import json

import pytest
from open_webui.tools import officecli


def test_attachment_filename_validation_is_workspace_only():
    assert officecli._validate_attachment_filename('chart.png') == 'chart.png'
    assert officecli._validate_attachment_filename('данные.csv') == 'данные.csv'

    with pytest.raises(ValueError):
        officecli._validate_attachment_filename('../chart.png')
    with pytest.raises(ValueError):
        officecli._validate_attachment_filename('/tmp/chart.png')
    with pytest.raises(ValueError):
        officecli._validate_attachment_filename('macro.exe')
    with pytest.raises(ValueError):
        officecli._validate_attachment_filename('presentation.pptx')


def test_office_command_allows_safe_picture_export():
    command = "get report.pptx '/slide[3]/picture[@id=7]' --save extracted.png --json"
    assert officecli._validate_command(command) == [
        'get',
        'report.pptx',
        '/slide[3]/picture[@id=7]',
        '--save',
        'extracted.png',
        '--json',
    ]


def test_office_attach_registers_and_publishes_extracted_files(monkeypatch, tmp_path):
    workspace = tmp_path / 'office-workspace'
    workspace.mkdir()
    (workspace / 'chart.png').write_bytes(b'png-content')
    (workspace / 'data.csv').write_text('name,value\nA,1\n', encoding='utf-8')

    registered_names = []
    published_items = []
    statuses = []

    monkeypatch.setattr(officecli, '_workspace', lambda metadata, user: workspace)

    async def fake_stage(workspace, metadata, user):
        return []

    async def fake_register(path, user, metadata):
        registered_names.append(path.name)
        is_image = path.suffix == '.png'
        return {
            'type': 'image' if is_image else 'file',
            'url': f'/files/{path.name}' if is_image else f'id-{path.name}',
            'id': f'id-{path.name}',
            'name': path.name,
        }

    async def fake_publish(items, metadata, emitter, chat_id, message_id):
        published_items.extend(items)
        assert chat_id == 'chat-1'
        assert message_id == 'message-1'
        return items, items

    async def fake_status(emitter, description, done=False, error=False):
        statuses.append((description, done, error))

    monkeypatch.setattr(officecli, '_stage_uploaded_files', fake_stage)
    monkeypatch.setattr(officecli, '_register_result', fake_register)
    monkeypatch.setattr(officecli, '_publish_result_files', fake_publish)
    monkeypatch.setattr(officecli, '_emit_status', fake_status)

    result = asyncio.run(
        officecli.office_attach(
            ['chart.png', 'data.csv', 'chart.png'],
            __user__={'id': 'user-1'},
            __metadata__={'chat_id': 'chat-1'},
            __chat_id__='chat-1',
            __message_id__='message-1',
        )
    )
    payload = json.loads(result)

    assert payload['ok'] is True
    assert payload['new_attachments'] == 2
    assert registered_names == ['chart.png', 'data.csv']
    assert [item['name'] for item in published_items] == ['chart.png', 'data.csv']
    assert statuses[-1] == ('Извлечённые файлы прикреплены к ответу', True, False)


def test_office_attach_rejects_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(officecli, '_workspace', lambda metadata, user: tmp_path)

    async def fake_stage(workspace, metadata, user):
        return []

    monkeypatch.setattr(officecli, '_stage_uploaded_files', fake_stage)

    with pytest.raises(ValueError, match='не найден'):
        asyncio.run(
            officecli.office_attach(
                ['missing.png'],
                __user__={'id': 'user-1'},
                __metadata__={'chat_id': 'chat-1'},
            )
        )
