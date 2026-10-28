"""Persistent aggregate discovery jobs over existing independently recorded tasks.

The coordinator queues platform tasks; the worker retains its browser lock and
may execute them serially. Anonymous jobs never open/login a platform session.
"""
import asyncio
import copy
import hashlib
import json
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from .db import now, uid
from .discovery import PLATFORMS, csv_text, result_list
from .models import Plan
from .planner import plan_request

Platform = str
DEFAULT_PLATFORMS = ['douyin', 'tiktok', 'instagram', 'youtube', 'facebook', 'linkedin', 'reddit']
FILTERS = ('matched', 'uncertain', 'excluded')


class DiscoveryJobRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request: str = Field(min_length=1, max_length=2000)
    platforms: list[Platform] = Field(default_factory=lambda: list(DEFAULT_PLATFORMS), min_length=1, max_length=40)
    limit: int = Field(default=10, ge=1, le=100)
    accessMode: Literal['anonymous'] = 'anonymous'
    keywords: list[str] | None = Field(default=None, max_length=3)
    requestId: str | None = Field(default=None, min_length=8, max_length=120, pattern=r'^[A-Za-z0-9_-]+$')

    @field_validator('request')
    @classmethod
    def request_not_blank(cls, value):
        if not value.strip():
            raise ValueError('找人需求不能为空')
        return value.strip()

    @field_validator('platforms')
    @classmethod
    def unique_platforms(cls, value):
        if any(p not in {item['id'] for item in PLATFORMS} for p in value):
            raise ValueError('平台不存在或尚未通过接入验收')
        if len(set(value)) != len(value):
            raise ValueError('平台不能重复')
        return value

    @field_validator('keywords')
    @classmethod
    def valid_keywords(cls, value):
        if value is None:
            return value
        if not value or any(not v.strip() or len(v.strip()) > 300 for v in value):
            raise ValueError('请提供1至3个非空搜索关键词，每个最多300字符')
        return list(dict.fromkeys(v.strip() for v in value))


def _identity(row):
    profile = row.get('profileUrl')
    if profile:
        try:
            p = urlsplit(profile)
            profile = urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), p.query, ''))
        except ValueError:
            pass
    return row['platform'], profile or row['id']


class DiscoveryJobs:
    def __init__(self, database, worker):
        self.db, self.worker = database, worker
        self._create_lock = asyncio.Lock()

    async def create(self, body: DiscoveryJobRequest):
        if not isinstance(body, DiscoveryJobRequest):
            body = DiscoveryJobRequest.model_validate(body)
        payload = body.model_dump(exclude={'requestId'})
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        async with self._create_lock:
            if body.requestId:
                old = next((j for j in self.db.all('discovery_jobs') if j.get('requestId') == body.requestId), None)
                if old:
                    if old['fingerprint'] != fingerprint:
                        raise ValueError('requestId 已用于不同的请求')
                    return self.snapshot(old['id'])
            planning = await plan_request(body.request, {})
            proposal = planning.get('plan') or {}
            words = body.keywords or [str(x).strip()[:300] for x in (proposal.get('keywords') or []) if str(x).strip()][:3]
            if not words:
                # Preserve the actual user request instead of inventing search terms.
                words = [body.request[:300]]
            stamp = now()
            record = {'id': uid('discovery'), **payload, 'requestId': body.requestId,
                      'fingerprint': fingerprint, 'status': 'queued', 'createdAt': stamp,
                      'updatedAt': stamp, 'finishedAt': None, 'cancelRequested': False,
                      'planning': {'provider': planning.get('provider', 'rules'), 'keywords': words,
                                   'questions': planning.get('questions', [])}, 'taskIds': []}
            tasks = []
            for platform in body.platforms:
                plan = Plan(platform=platform, name=f"{platform} · {body.request[:80]}",
                            target=body.request, region=str(proposal.get('region') or '')[:200],
                            signals=str(proposal.get('signals') or '')[:2000],
                            sourceType='public_search', keywords=words, sourceUrl='',
                            workKeywords=[], maxWorks=5, maxComments=1,
                            scanLimit=min(30, max(body.limit, 3)), limit=min(body.limit, 30),
                            mode='find', authorized=False, channel='dm', scheduleMode='once',
                            communicationStrategy='').model_dump()
                task = {'id': uid('task'), 'jobId': record['id'], 'accountId': 'local',
                        'plan': plan, 'status': 'ready', 'createdAt': stamp, 'updatedAt': stamp,
                        'lastRunAt': None, 'nextRunAt': None, 'demo': False}
                record['taskIds'].append(task['id'])
                tasks.append(task)
            # Commit the entire ownership graph before any worker can start.
            with self.db.lock, self.db.conn:
                for task in tasks:
                    self.db.conn.execute('INSERT INTO records VALUES(?,?,?)',
                                         ('tasks', task['id'], json.dumps(task, ensure_ascii=False)))
                self.db.conn.execute('INSERT INTO records VALUES(?,?,?)',
                                     ('discovery_jobs', record['id'], json.dumps(record, ensure_ascii=False)))
            self.db.event('discovery.job.created', {'id': record['id'], 'taskIds': record['taskIds']})
            for task in tasks:
                self.db.event('task.created', task)
                try:
                    self.worker.run(task['id'])
                except Exception as error:
                    task.update(status='failed', reason=str(error)[:1000], updatedAt=now())
                    self.db.put('tasks', task)
                    self.db.event('task.updated', task)
            return self.snapshot(record['id'])

    def _record(self, job_id):
        record = self.db.get('discovery_jobs', job_id)
        if record is None:
            raise KeyError(job_id)
        return record

    def snapshot(self, job_id, status=None):
        if status is not None and status not in FILTERS:
            raise ValueError('无效判断状态')
        record = self._record(job_id)
        executions = self.db.all('executions')
        children, rows = [], []
        for task_id in record['taskIds']:
            task = self.db.get('tasks', task_id)
            if task is None:
                children.append({'taskId': task_id, 'status': 'failed', 'reason': '子任务记录缺失', 'counts': {}})
                continue
            runs = sorted((e for e in executions if e.get('taskId') == task_id), key=lambda e: e.get('startedAt', ''), reverse=True)
            latest = runs[0] if runs else None
            result = result_list(self.db, task_id)
            rows.extend(result['items'])
            children.append({'taskId': task_id, 'platform': task['plan']['platform'],
                             'sourceType': task['plan']['sourceType'], 'status': task['status'],
                             'reason': task.get('reason') or (latest or {}).get('reason'),
                             'counts': result['counts'], 'total': result['total'],
                             'executionId': latest['id'] if latest else None,
                             'steps': latest.get('steps', []) if latest else []})
        unique = {}
        for row in rows:
            key = _identity(row)
            if key not in unique:
                unique[key] = copy.deepcopy(row)
                unique[key]['taskIds'] = [row['taskId']]
                continue
            old = unique[key]
            old['taskIds'] = list(dict.fromkeys(old['taskIds'] + [row['taskId']]))
            known = {(s.get('id'), s.get('url'), s.get('text')) for s in old['sources']}
            old['sources'].extend(copy.deepcopy(s) for s in row['sources'] if (s.get('id'), s.get('url'), s.get('text')) not in known)
            if old['match'].get('status') != row['match'].get('status'):
                old['match'] = {'status': 'uncertain', 'provider': 'aggregation',
                                'reasons': ['同一平台身份的判断存在差异，保留来源待核实'], 'missing': ['需复核各来源判断']}
        order = {p: n for n, p in enumerate(record['platforms'])}
        items = sorted(unique.values(), key=lambda r: (FILTERS.index(r['match']['status']) if r['match'].get('status') in FILTERS else 1,
                                                       order.get(r['platform'], 99), r.get('profileUrl') or r['id']))
        counts = {s: sum(r['match'].get('status') == s for r in items) for s in FILTERS}
        filtered = [r for r in items if status is None or r['match'].get('status') == status]
        delivered = filtered[:record['limit']]
        states = [c['status'] for c in children]
        live = any(not job.done() for key, job in self.worker.jobs.items() if key in record['taskIds'])
        if record.get('cancelRequested'):
            aggregate = 'cancelling' if live else 'cancelled'
        elif any(s in ('ready', 'queued', 'running') for s in states) and not live:
            aggregate = 'partial' if any(s == 'completed' for s in states) or items else 'interrupted'
        elif 'running' in states:
            aggregate = 'running'
        elif any(s in ('ready', 'queued') for s in states):
            aggregate = 'queued'
        elif states and all(s == 'completed' for s in states):
            aggregate = 'completed'
        elif any(s in ('paused', 'partial') for s in states):
            aggregate = 'partial' if any(s == 'completed' for s in states) or items else 'interrupted'
        elif any(s == 'completed' for s in states) or items:
            aggregate = 'partial'
        elif states and all(s == 'cancelled' for s in states):
            aggregate = 'cancelled'
        else:
            aggregate = 'failed'
        changed = record['status'] != aggregate
        if changed:
            record['status'] = aggregate
            record['updatedAt'] = now()
        terminal = aggregate in ('completed', 'failed', 'partial', 'interrupted', 'cancelled')
        if terminal and not record.get('finishedAt'):
            record['finishedAt'] = now()
            changed = True
        if not terminal and record.get('finishedAt'):
            record['finishedAt'] = None
            changed = True
        if changed:
            self.db.put('discovery_jobs', record)
        public = {k: v for k, v in record.items() if k not in ('fingerprint',)}
        return {**public, 'children': children, 'counts': {**counts, 'observed': len(items), 'delivered': len(delivered)},
                'items': delivered, 'filter': status or 'all', 'hasMore': len(filtered) > len(delivered),
                'progress': {'totalPlatforms': len(children), 'finishedPlatforms': sum(s in ('completed', 'failed', 'cancelled', 'paused', 'partial') for s in states)},
                'scope': 'job-platform-identity', 'currentIntentVerified': False,
                'goalMet': counts['matched'] >= record['limit']}

    def export(self, job_id, status='matched'):
        return csv_text(self.snapshot(job_id, status=status))

    def cancel(self, job_id):
        record = self._record(job_id)
        current = self.snapshot(job_id)
        if current['status'] in ('completed', 'failed', 'partial', 'interrupted', 'cancelled'):
            return current
        record.update(cancelRequested=True, updatedAt=now())
        self.db.put('discovery_jobs', record)
        for task_id in record['taskIds']:
            task = self.db.get('tasks', task_id)
            if task and task['status'] in ('ready', 'queued', 'running', 'paused'):
                self.worker.control(task_id, 'cancel')
        self.db.event('discovery.job.cancelled', {'id': job_id})
        return self.snapshot(job_id)

    def list(self):
        return [{k: v for k, v in self.snapshot(j['id']).items() if k != 'items'} for j in self.db.all('discovery_jobs')]
