import asyncio
import json

from open_webui.internal.agents import _ragflow_citation_sources, _stream_with_sources


def test_ragflow_citations_keep_secure_document_reference():
    sources = _ragflow_citation_sources(
        [
            {
                'dataset_id': 'dataset-1',
                'document_id': 'document-1',
                'name': 'Регламент.docx',
                'dataset_name': 'Регламенты',
                'space_name': 'Корпоративное пространство',
                'parts': [{'content': 'Фрагмент', 'similarity': 0.91, 'page': 2}],
            }
        ]
    )

    assert sources[0]['source'] == {
        'id': 'ragflow:dataset-1:document-1',
        'name': 'Регламент.docx',
        'type': 'ragflow',
        'url': '/api/v1/ragflow/datasets/dataset-1/documents/document-1/content',
    }
    assert sources[0]['metadata'][0]['space_name'] == 'Корпоративное пространство'
    assert sources[0]['metadata'][0]['dataset_name'] == 'Регламенты'
    assert sources[0]['metadata'][0]['page'] == 2
    assert sources[0]['distances'] == [0.91]


def test_ragflow_sources_are_first_stream_event():
    sources = [{'source': {'id': 'source-1', 'name': 'Документ'}}]

    async def upstream():
        yield 'data: {"choices":[]}\n\n'

    async def collect():
        return [item async for item in _stream_with_sources(upstream(), sources)]

    events = asyncio.run(collect())
    assert json.loads(events[0].removeprefix('data: ').strip()) == {'sources': sources}
    assert events[1] == 'data: {"choices":[]}\n\n'
