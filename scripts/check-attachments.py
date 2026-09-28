"""Live attachment lifecycle checks. Uses a dedicated local test account."""
import json
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://localhost:8080/api'
REPORT = {}


def login(username, password, register=False):
    client = httpx.Client(base_url=BASE, timeout=90)
    client.headers['X-CSRF-TOKEN'] = client.get('/auth/csrf').json()['token']
    if register:
        response = client.post('/auth/register', json={'username': username, 'password': password})
        assert response.status_code in (200, 409), response.text
    client.post('/auth/login', json={'username': username, 'password': password}).raise_for_status()
    client.headers['X-CSRF-TOKEN'] = client.get('/auth/csrf').json()['token']
    return client


def upload(client, name, content, scope):
    response = client.post('/documents', files={'file': (name, content)}, data={'scope': scope})
    response.raise_for_status()
    return response.json()['id']


def ready(client, document):
    for _ in range(90):
        response = client.get(f'/documents/{document}')
        response.raise_for_status()
        row = response.json()
        if row['status'] != 'INDEXING':
            assert row['status'] == 'READY', row
            return row
        time.sleep(1)
    raise AssertionError('Index timeout')


if __name__ == '__main__':
    client = login('qa_attachment_0903', 'FinancialTest_2026!', True)
    private = upload(client, '本次核查说明.txt', '测试样本，非真实企业数据。2025 年营业收入为 125.00 百万元，2024 年为 100.00 百万元。'.encode(), 'TASK')
    ready(client, private)
    assert private not in [doc['id'] for doc in client.get('/documents').json()]
    REPORT['hidden_from_library'] = True
    other = login('qa_browser_0903', 'FinancialTest_2026!')
    for path in [f'/documents/{private}', f'/documents/{private}/source']:
        assert other.get(path).status_code == 404
    assert other.delete(f'/documents/{private}').status_code == 404
    REPORT['cross_owner_denied'] = True
    session = client.post('/sessions', json={'title': '附件生命周期验收'}).json()['id']
    body = {'session_id': session, 'document_ids': [private], 'instruction': '仅根据附件，测试样本2025年的营业收入是多少？给出单位和引用，明确这是测试数据。', 'idempotency_key': str(uuid.uuid4())}
    response = client.post('/tasks', json=body)
    response.raise_for_status()
    task = response.json()['id']
    assert client.post('/tasks', json=body).json()['id'] == task
    assert client.post('/tasks', json={**body, 'idempotency_key': str(uuid.uuid4())}).status_code == 409
    assert client.delete(f'/documents/{private}').status_code == 409
    REPORT['single_task_binding_and_idempotency'] = True
    for _ in range(180):
        detail = client.get(f'/tasks/{task}').json()
        if detail['status'] not in ('QUEUED', 'RUNNING'):
            break
        time.sleep(1)
    assert detail['status'] == 'SUCCEEDED', detail
    assert detail['evidence'] and all(e['document_id'] == private for e in detail['evidence'])
    assert '125' in detail['result'] and '[E:' in detail['result']
    assert client.get(f'/documents/{private}/source').status_code == 200
    REPORT['private_task_with_real_model'] = {'id': task, 'result': detail['result']}
    library = upload(client, '可复用测试说明.txt', b'Library sample: Revenue 88 million CNY.', 'LIBRARY')
    ready(client, library)
    assert library in [doc['id'] for doc in client.get('/documents').json()]
    assert client.delete(f'/documents/{library}').status_code == 409
    REPORT['library_visible_and_not_discarded'] = True
    draft = upload(client, '待移除附件.txt', b'Discard this attachment.', 'TASK')
    response = client.delete(f'/documents/{draft}')
    response.raise_for_status()
    time.sleep(3)
    assert client.get(f'/documents/{draft}').status_code == 404
    assert client.get(f'/documents/{draft}/source').status_code == 404
    assert client.post('/tasks', json={**body, 'document_ids': [draft], 'idempotency_key': str(uuid.uuid4())}).status_code == 409
    owner = client.get('/auth/me').json()['id']
    assert not (ROOT / f'.runtime/rag/{owner}_{draft}.json').exists()
    REPORT['discard_during_index_does_not_resurrect'] = True
    (ROOT / '.runtime/attachment-checks.json').write_text(json.dumps(REPORT, ensure_ascii=False, indent=2))
    print(json.dumps(REPORT, ensure_ascii=False, indent=2))
