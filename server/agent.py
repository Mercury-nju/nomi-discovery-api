import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .db import now, uid
from .planner import assess
from .discovery import discovery_only, validate_execution

logger = logging.getLogger('uvicorn.error')


def next_daily(plan):
    if plan['scheduleMode'] != 'daily':
        return None
    current = datetime.now(ZoneInfo('Asia/Shanghai'))
    hour, minute = map(int, plan['scheduleTime'].split(':'))
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return target.isoformat()


class Agent:
    def __init__(self, db, adapter, adapters=None):
        self.db, self.adapter = db, adapter
        self.adapters = adapters or {}
        self.browser_lock = asyncio.Lock()
        self.jobs = {}
        self.scheduler_task = None
        self.stopping = False

    def log(self, event, execution=None, **values):
        logger.info(json.dumps({'event': event, 'at': now(), **({'taskId': execution['taskId'], 'executionId': execution['id']} if execution else {}), **values}, ensure_ascii=False))

    def step(self, execution, name, status, reason=None):
        """A step is current state; its event stream retains every transition."""
        timestamp = now()
        previous = next((item for item in execution['steps'] if item['name'] == name), None)
        update = {'name': name, 'status': status, 'time': timestamp, 'reason': reason}
        if previous:
            previous.update(update)
        else:
            execution['steps'].append({**update, 'startedAt': timestamp})
        self.db.put('executions', execution)
        self.db.event('execution.step', {'executionId': execution['id'], 'taskId': execution['taskId'], **update})
        self.db.event('execution.updated', execution)
        self.log('step', execution, name=name, status=status, reason=reason)

    def finish_steps(self, execution, status, reason=None):
        for step in list(execution['steps']):
            if step['status'] in ('running', 'pending'):
                self.step(execution, step['name'], status, reason or step.get('reason'))

    async def start(self):
        self.db.recover_sends()
        for execution in self.db.all('executions'):
            if execution['status'] == 'running':
                execution.update(status='partial', finishedAt=now(), reason='服务重启，原执行已中断；不会自动重跑。')
                self.finish_steps(execution, 'cancelled', execution['reason'])
                self.db.put('executions', execution)
            elif any(step['status'] in ('running', 'pending') for step in execution.get('steps', [])):
                terminal = 'completed' if execution['status'] == 'completed' else 'cancelled' if execution['status'] == 'cancelled' else 'failed'
                self.finish_steps(execution, terminal, execution.get('reason'))
        for task in self.db.all('tasks'):
            if task['status'] in ('running', 'queued'):
                task.update(status='paused', updatedAt=now(), reason='服务重启后暂停，请检查记录再继续。')
                self.db.put('tasks', task)
            elif task['status'] not in ('paused', 'cancelled') and task['plan']['scheduleMode'] == 'daily' and task.get('nextRunAt'):
                if datetime.fromisoformat(task['nextRunAt']) <= datetime.now(ZoneInfo('Asia/Shanghai')):
                    skipped = task['nextRunAt']
                    note = '服务停止期间错过的计划已跳过，不补执行；按下一次时间继续。'
                    task.update(nextRunAt=next_daily(task['plan']), updatedAt=now(), scheduleNote=note)
                    self.db.put('tasks', task)
                    self.db.event('schedule.skipped', {'taskId': task['id'], 'skippedAt': skipped, 'nextRunAt': task['nextRunAt'], 'reason': note})
                    self.db.event('task.updated', task)
                    self.log('schedule.skipped', taskId=task['id'], skippedAt=skipped, nextRunAt=task['nextRunAt'])
        self.scheduler_task = asyncio.create_task(self.scheduler())

    async def stop(self):
        self.stopping = True
        if self.scheduler_task:
            self.scheduler_task.cancel()
        for job in self.jobs.values():
            job.cancel()
        if self.jobs:
            await asyncio.gather(*self.jobs.values(), return_exceptions=True)
        await self.adapter.close()
        for platform_adapter in self.adapters.values():
            await platform_adapter.close()

    async def scheduler(self):
        while not self.stopping:
            if (self.db.get('settings', 'conversation-monitor') or {}).get('value', {}).get('enabled'):
                await asyncio.sleep(3)
                continue
            for task in self.db.all('tasks'):
                if (discovery_only() and task['plan'].get('mode') != 'find'):
                    continue
                try:
                    validate_execution(task['plan'])
                except ValueError:
                    continue
                if task['plan'].get('platform', 'douyin') != 'douyin' and task['plan']['platform'] not in self.adapters:
                    continue
                if task.get('nextRunAt') and task['status'] not in ('paused', 'cancelled', 'running', 'queued'):
                    if datetime.fromisoformat(task['nextRunAt']) <= datetime.now(ZoneInfo('Asia/Shanghai')):
                        self.run(task['id'])
            await asyncio.sleep(3)

    def run(self, task_id):
        if (self.db.get('settings', 'conversation-monitor') or {}).get('value', {}).get('enabled'):
            raise ValueError('私信承接监听中，请先停止监听再运行找客任务；本版将两种浏览器工作分时执行。')
        task = self.db.get('tasks', task_id)
        if not task:
            raise ValueError('任务不存在')
        validate_execution(task['plan'])
        if task['plan'].get('platform', 'douyin') != 'douyin' and task['plan']['platform'] not in self.adapters:
            raise ValueError('平台采集器未配置')
        if task_id in self.jobs and not self.jobs[task_id].done():
            raise ValueError('任务已经排队或执行中')
        task.update(status='queued', updatedAt=now(), reason=None)
        self.db.put('tasks', task)
        self.db.event('task.updated', task)
        job = asyncio.create_task(self.execute(task_id))
        self.jobs[task_id] = job
        return task

    def control(self, task_id, action):
        task = self.db.get('tasks', task_id)
        if not task:
            raise ValueError('任务不存在')
        if action == 'resume':
            job = self.jobs.get(task_id)
            if job and not job.done():
                raise ValueError('上一轮仍在停止，请等待执行结束后恢复')
            task.update(status='ready', updatedAt=now(), nextRunAt=next_daily(task['plan']))
        else:
            task.update(status='paused' if action == 'pause' else 'cancelled', updatedAt=now())
            if action == 'cancel':
                task['nextRunAt'] = None
        self.db.put('tasks', task)
        self.db.event('task.updated', task)
        return task

    def cancelled(self, task_id):
        task = self.db.get('tasks', task_id)
        return self.stopping or not task or task['status'] in ('paused', 'cancelled')

    async def save_customer(self, raw, task, execution):
        stable = raw.get('platformId') or raw.get('profileUrl')
        platform = task['plan'].get('platform', 'douyin')
        if stable and platform != 'douyin':
            stable = platform + ':' + stable
        if not stable:
            # Names alone are not stable user identities and are never merged.
            identity = uid('customer')
        else:
            identity = 'customer-' + hashlib.sha256(stable.encode()).hexdigest()[:24]
        existing = self.db.get('customers', identity)
        customer = existing or {'id': identity, 'accountId': 'local', 'taskIds': [], 'discoveredAt': now(), 'messages': [], 'sources': [], 'demo': False}
        for key in ('platformId', 'profileUrl', 'avatarUrl', 'nickname', 'profileText', 'liveContext', 'commentContext', 'entityType'):
            if raw.get(key):
                customer[key] = raw[key]
        customer['taskIds'] = list(dict.fromkeys(customer['taskIds'] + [task['id']]))
        seen = {x['id'] for x in customer['sources']}
        for source in raw.get('sources', []):
            observation_id = f"{source['id']}:{execution['id']}" if source.get('id') else uid('source')
            source = {**source, 'id': observation_id, 'taskId': task['id'], 'executionId': execution['id'], 'accountId': 'local', 'demo': False}
            if source['id'] not in seen:
                customer['sources'].append(source)
                seen.add(source['id'])
        scoped = {**customer, 'sources': [x for x in customer['sources'] if x.get('executionId') == execution['id']]}
        match = await assess(scoped, task['plan'])
        customer['match'] = match
        customer.setdefault('matches', {})[task['id']] = match
        customer.setdefault('executionMatches', {})[execution['id']] = match
        customer['target'] = match['status'] == 'matched'
        self.db.put('customers', customer)
        self.db.event('customer.updated', customer)
        return customer

    async def execute(self, task_id):
        execution = None
        try:
            async with self.browser_lock:
                if self.cancelled(task_id):
                    return
                task = self.db.get('tasks', task_id)
                task.update(status='running', lastRunAt=now(), updatedAt=now())
                self.db.put('tasks', task)
                execution = {'id': uid('execution'), 'taskId': task_id, 'status': 'running', 'startedAt': now(), 'finishedAt': None, 'steps': [], 'analyzed': 0, 'targeted': 0, 'contacted': 0, 'leads': 0, 'customerIds': []}
                self.db.put('executions', execution)
                self.db.event('task.updated', task)
                self.db.event('execution.updated', execution)
                self.log('run.started', execution, sourceType=task['plan']['sourceType'], targetLimit=task['plan']['limit'], scanLimit=task['plan'].get('scanLimit', 100), observeSeconds=task['plan'].get('observeSeconds'))
                observed = {}
                async def observe(candidate):
                    key = candidate.get('platformId') or candidate.get('profileUrl') or json.dumps([candidate.get('nickname'), candidate.get('sources')], sort_keys=True, ensure_ascii=False)
                    if key in observed:
                        old = observed[key]
                        existing_sources = {s['id'] for s in old.get('sources', [])}
                        if not any(f"{s['id']}:{execution['id']}" not in existing_sources for s in candidate.get('sources', []) if s.get('id')):
                            return old
                        self.step(execution, '判断公开证据', 'running', f"正在复核第 {execution['analyzed']} 位用户的新发言")
                        customer = await self.save_customer(candidate, task, execution)
                        execution['targeted'] += int(customer['target']) - int(old['target'])
                        observed[key] = customer
                        self.db.put('executions', execution)
                        self.db.event('execution.updated', execution)
                        self.step(execution, '判断公开证据', 'completed', f"已分析 {execution['analyzed']} 人，明确匹配 {execution['targeted']} 人")
                        self.log('candidate.assessed', execution, customerId=customer['id'], status=customer['match']['status'], provider=customer['match'].get('provider'), analyzed=execution['analyzed'], targeted=execution['targeted'])
                        return customer
                    self.step(execution, '判断公开证据', 'running', f"正在分析第 {execution['analyzed'] + 1} 位用户")
                    customer = await self.save_customer(candidate, task, execution)
                    observed[key] = customer
                    execution['customerIds'].append(customer['id'])
                    execution['analyzed'] += 1
                    execution['targeted'] += int(customer['target'])
                    self.db.put('executions', execution)
                    self.db.event('execution.updated', execution)
                    self.step(execution, '判断公开证据', 'completed', f"已分析 {execution['analyzed']} 人，明确匹配 {execution['targeted']} 人")
                    self.log('candidate.assessed', execution, customerId=customer['id'], status=customer['match']['status'], provider=customer['match'].get('provider'), analyzed=execution['analyzed'], targeted=execution['targeted'])
                    return customer
                async def emit(event):
                    if event.get('type') == 'candidate' and event.get('customer'):
                        customer = await observe(event['customer'])
                        return {'matched': customer['target'], 'status': customer['match']['status'], 'customerId': customer['id']}
                    else:
                        step_status = event.get('status', 'running')
                        if self.cancelled(task_id) and step_status in ('running', 'completed'):
                            step_status = 'cancelled'
                        self.step(execution, event.get('name') or '执行中', step_status, event.get('reason') or event.get('text'))
                self.step(execution, '校验公开搜索', 'running')
                active_adapter = self.adapters.get(task['plan'].get('platform', 'douyin')) or self.adapter
                status = await active_adapter.status()
                if not status.get('connected'):
                    raise ValueError(status.get('reason') or '请检查所选平台的连接配置')
                self.step(execution, '校验公开搜索', 'completed', status.get('reason') or '平台执行条件已满足')
                raw = await active_adapter.discover(task['plan'], emit, lambda: self.cancelled(task_id))
                for candidate in raw:
                    # Keep evidence already observed even if the user paused meanwhile.
                    await observe(candidate)
                for customer in observed.values():
                    self.db.put('executions', execution)
                    self.db.event('execution.updated', execution)
                was_cancelled = self.cancelled(task_id)
                execution.update(status='cancelled' if was_cancelled else 'completed', finishedAt=now())
                self.finish_steps(execution, 'cancelled' if was_cancelled else 'completed', '本轮已取消，保留已采集证据' if was_cancelled else None)
                if not raw and not was_cancelled:
                    execution['reason'] = '本轮未取得可解析用户；未编造结果。请查看步骤中的跳过或限制原因。'
                elif not was_cancelled and execution['targeted'] < task['plan']['limit']:
                    execution['reason'] = f"本轮分析 {execution['analyzed']} 人，明确匹配 {execution['targeted']} 人；未达到 {task['plan']['limit']} 人目标，待核实用户未计入目标。"
                self.db.put('executions', execution)
                self.db.event('execution.updated', execution)
                self.log('run.finished', execution, status=execution['status'], analyzed=execution['analyzed'], targeted=execution['targeted'], contacted=execution['contacted'], reason=execution.get('reason'))
                latest = self.db.get('tasks', task_id)
                if latest['status'] not in ('paused', 'cancelled'):
                    latest.update(status='completed', updatedAt=now(), nextRunAt=next_daily(task['plan']))
                    self.db.put('tasks', latest)
                    self.db.event('task.updated', latest)
        except asyncio.CancelledError:
            if execution:
                execution.update(status='cancelled', finishedAt=now(), reason='执行服务停止；未自动重发任何消息。')
                self.finish_steps(execution, 'cancelled', execution['reason'])
                self.db.put('executions', execution)
                self.log('run.cancelled', execution)
            raise
        except Exception as error:
            reason = str(error)[:1500]
            if execution:
                execution.update(status='partial' if execution['analyzed'] else 'failed', finishedAt=now(), reason=reason)
                self.finish_steps(execution, 'failed', reason)
                self.db.put('executions', execution)
                self.db.event('execution.updated', execution)
                self.log('run.failed', execution, reason=reason, analyzed=execution['analyzed'])
            task = self.db.get('tasks', task_id)
            if task and task['status'] not in ('paused', 'cancelled'):
                task.update(status='failed', updatedAt=now(), reason=reason, nextRunAt=next_daily(task['plan']))
                self.db.put('tasks', task)
                self.db.event('task.updated', task)

    def knowledge(self):
        return (self.db.get('settings', 'knowledge') or {'value': {}})['value']

