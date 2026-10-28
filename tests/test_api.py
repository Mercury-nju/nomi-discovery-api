import time
from fastapi.testclient import TestClient
from server.api import create_app
from server.discovery import PLATFORMS


class Adapter:
    async def status(self):
        return {'connected': True}

    async def close(self):
        pass

    async def discover(self, plan, emit, cancelled):
        assert plan['sourceType'] == 'public_search' and plan['mode'] == 'find'
        return [{'platformId': 'example', 'nickname': 'Example',
                 'profileUrl': 'https://www.reddit.com/user/example/',
                 'sources': [{'id': 'evidence', 'type': 'search_snippet',
                              'evidenceLevel': 'search_snippet', 'verifiedStatement': False,
                              'text': 'Public indexed business profile',
                              'url': 'https://www.reddit.com/user/example/'}]}]


def app(tmp_path, **kwargs):
    return create_app(tmp_path, {p['id']: Adapter() for p in PLATFORMS}, **kwargs)


def test_real_orchestration_and_export(tmp_path):
    with TestClient(app(tmp_path, api_key='secret')) as c:
        assert c.get('/api/health').status_code == 401
        c.headers['Authorization'] = 'Bearer secret'
        assert c.get('/api/health').json()['platformCount'] == 18
        assert all(p['capabilities'] == ['public_search'] for p in c.get('/api/platforms').json()['platforms'])
        body = {'request':'Find public business profiles', 'platforms':['reddit'],
                'keywords':['business'], 'limit':1, 'requestId':'test-request-123'}
        r=c.post('/api/discovery/jobs',json=body)
        assert r.status_code == 202, r.text
        job=r.json()['id']
        for _ in range(200):
            result=c.get('/api/discovery/jobs/'+job).json()
            if result['status'] not in ('running','queued','planning'):
                break
            time.sleep(.01)
        assert result['status'] == 'completed', result
        assert result['counts']['matched'] == 0
        assert result['counts']['uncertain'] == 1
        assert len(result['items']) == 1
        assert c.post('/api/discovery/jobs',json=body).json()['id'] == job
        assert c.get('/api/discovery/jobs/'+job+'/export?status=uncertain').content.startswith(b'\xef\xbb\xbf')
        assert c.get('/api/discovery/jobs/'+job+'?status=all').status_code == 422
        assert c.get('/api/discovery/jobs/missing').status_code == 404
        assert c.get('/api/discovery/jobs/missing/export').status_code == 404
        assert c.post('/api/discovery/jobs/missing/cancel').status_code == 404
        assert c.post('/api/customers/example/send',json={}).status_code == 404
        assert c.post('/api/discovery/jobs',json={**body,'mode':'contact'}).status_code == 422


def test_local_origin_and_remote_boundary(tmp_path):
    with TestClient(app(tmp_path, api_key='', cors_origins=['http://localhost:5173'])) as c:
        assert c.get('/api/health').status_code == 200
        assert c.get('/api/health',headers={'Host':'evil.example'}).status_code == 403
        assert c.get('/api/health',headers={'Origin':'https://evil.example'}).status_code == 403
        assert c.get('/api/health',headers={'Origin':'http://localhost:5173'}).headers['access-control-allow-origin'] == 'http://localhost:5173'
    with TestClient(app(tmp_path/'remote', api_key='secret'), client=('203.0.113.1',1234)) as c:
        assert c.get('/api/health',headers={'Authorization':'Bearer secret','Host':'api.example'}).status_code == 200
    with TestClient(app(tmp_path/'no-key', api_key=''), client=('203.0.113.1',1234)) as c:
        assert c.get('/api/health').status_code == 403
