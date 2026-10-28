"""Run against a started API: python example_client.py (stdlib only)."""
import json
import os
import time
import urllib.request

base = os.getenv('DISCOVERY_API_URL', 'http://127.0.0.1:8766').rstrip('/')
headers = {'Content-Type': 'application/json'}
if os.getenv('NOMI_API_KEY'):
    headers['Authorization'] = 'Bearer ' + os.environ['NOMI_API_KEY']


def call(path, body=None):
    request = urllib.request.Request(base + path, headers=headers,
        data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


if __name__ == '__main__':
    job = call('/api/discovery/jobs', {
        'request': 'Find public software development business candidates in London',
        'platforms': ['github', 'clutch'],
        'keywords': ['software developer London'],
        'limit': 5,
        'accessMode': 'anonymous',
    })
    for _ in range(120):
        job = call('/api/discovery/jobs/' + job['id'])
        print(job['status'], job['counts'])
        if job['status'] in {'completed', 'partial', 'failed', 'cancelled', 'interrupted'}:
            print(json.dumps(job['items'], ensure_ascii=False, indent=2))
            break
        time.sleep(3)
    else:
        print('Still running. Query job later:', job['id'])
