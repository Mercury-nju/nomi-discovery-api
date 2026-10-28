"""Standalone, single-tenant discovery API. No UI or outreach routes."""
import copy
import ipaddress
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from .agent import Agent
from .db import Database
from .discovery import PLATFORMS
from .discovery_jobs import DiscoveryJobs, DiscoveryJobRequest
from .public_search import PublicSearchAdapter


def create_app(data_dir=None, adapters=None, api_key=None, cors_origins=None):
    directory = Path(data_dir or os.getenv('NOMI_DATA_DIR', '.data')).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    database = Database(directory / 'discovery.sqlite3')
    adapters = adapters if adapters is not None else {
        p['id']: PublicSearchAdapter(directory, p['id']) for p in PLATFORMS}
    worker = Agent(database, adapters['douyin'], adapters)
    jobs = DiscoveryJobs(database, worker)
    key = os.getenv('NOMI_API_KEY', '') if api_key is None else api_key
    origins = cors_origins if cors_origins is not None else [
        item.strip() for item in os.getenv('NOMI_ALLOWED_ORIGINS', '').split(',') if item.strip()]
    if '*' in origins:
        raise ValueError('Configure exact CORS origins instead of wildcard')

    @asynccontextmanager
    async def lifespan(application):
        await worker.start()
        try:
            yield
        finally:
            await worker.stop()
            database.close()

    app = FastAPI(title='Nomi Discovery API', version='1.0.0', lifespan=lifespan)
    app.state.db, app.state.agent, app.state.discovery_jobs = database, worker, jobs
    app.add_middleware(CORSMiddleware, allow_origins=origins,
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'Authorization'])

    @app.middleware('http')
    async def access(request: Request, call_next):
        origin = request.headers.get('origin')
        if origin and origin not in origins:
            return JSONResponse({'detail': 'Origin is not allowed'}, status_code=403)
        if key:
            # CORS preflight contains no bearer token; it grants no data access.
            if request.method != 'OPTIONS' and not secrets.compare_digest(
                    request.headers.get('authorization', ''), 'Bearer ' + key):
                return JSONResponse({'detail': 'Bearer API key required'}, status_code=401)
        else:
            peer = request.client.host if request.client else ''
            try:
                local = ipaddress.ip_address(peer).is_loopback
            except ValueError:
                local = peer == 'testclient'
            host = request.url.hostname
            if not local or host not in ('localhost', '127.0.0.1', '::1', 'testserver'):
                return JSONResponse({'detail': 'Set NOMI_API_KEY for remote access'}, status_code=403)
        if request.method == 'POST' and request.headers.get('sec-fetch-site') == 'cross-site' and not origin:
            return JSONResponse({'detail': 'Cross-site request rejected'}, status_code=403)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def invalid(_, error):
        return JSONResponse({'detail': str(error)}, status_code=409)

    @app.get('/api/health')
    async def health():
        return {'ok': True, 'version': '1.0.0', 'discoveryOnly': True,
                'accessMode': 'anonymous', 'platformCount': len(PLATFORMS)}

    @app.get('/api/platforms')
    async def platforms():
        return {'platforms': copy.deepcopy(PLATFORMS)}

    @app.post('/api/discovery/jobs', status_code=202)
    async def create(body: DiscoveryJobRequest):
        return await jobs.create(body)

    @app.get('/api/discovery/jobs')
    async def listing():
        return jobs.list()

    def checked_status(status):
        if status is not None and status not in ('matched', 'uncertain', 'excluded'):
            raise HTTPException(422, 'Invalid result status')

    @app.get('/api/discovery/jobs/{job_id}')
    async def get(job_id: str, status: str | None = None):
        checked_status(status)
        try:
            return jobs.snapshot(job_id, status)
        except KeyError:
            raise HTTPException(404, 'Discovery job not found')

    @app.get('/api/discovery/jobs/{job_id}/export')
    async def export(job_id: str, status: str = 'matched'):
        checked_status(status)
        try:
            return Response(jobs.export(job_id, status), media_type='text/csv; charset=utf-8',
                            headers={'Content-Disposition': f'attachment; filename="discovery-{status}.csv"'})
        except KeyError:
            raise HTTPException(404, 'Discovery job not found')

    @app.post('/api/discovery/jobs/{job_id}/cancel')
    async def cancel(job_id: str):
        try:
            return jobs.cancel(job_id)
        except KeyError:
            raise HTTPException(404, 'Discovery job not found')

    return app


app = create_app()
