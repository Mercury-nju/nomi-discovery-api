"""SQLite is the source of truth. Browser sessions and credentials never enter API records."""
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return f'{prefix}-{uuid.uuid4().hex}'


class Database:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.conn:
            self.conn.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS records(kind TEXT NOT NULL,id TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT NOT NULL,kind TEXT NOT NULL,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sends(id TEXT PRIMARY KEY,customer_id TEXT NOT NULL,channel TEXT NOT NULL,state TEXT NOT NULL,data TEXT NOT NULL);
            ''')

    def put(self, kind, record):
        with self.lock, self.conn:
            self.conn.execute('INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data', (kind, record['id'], json.dumps(record, ensure_ascii=False)))
        return record

    def get(self, kind, identity):
        with self.lock:
            row = self.conn.execute('SELECT data FROM records WHERE kind=? AND id=?', (kind, identity)).fetchone()
        return json.loads(row['data']) if row else None

    def all(self, kind):
        with self.lock:
            rows = self.conn.execute('SELECT data FROM records WHERE kind=? ORDER BY rowid DESC', (kind,)).fetchall()
        return [json.loads(row['data']) for row in rows]

    def event(self, kind, data):
        at = now()
        with self.lock, self.conn:
            cursor = self.conn.execute('INSERT INTO events(at,kind,data) VALUES(?,?,?)', (at, kind, json.dumps(data, ensure_ascii=False)))
        return {'id': cursor.lastrowid, 'at': at, 'kind': kind, 'data': data}

    def events(self, after=0):
        with self.lock:
            rows = self.conn.execute('SELECT * FROM events WHERE id>? ORDER BY id LIMIT 250', (after,)).fetchall()
        result = [{'id': row['id'], 'at': row['at'], 'kind': row['kind'], 'data': json.loads(row['data'])} for row in rows]
        return {'events': result, 'cursor': result[-1]['id'] if result else after}

    def reserve_send(self, identity, customer_id, channel, data):
        with self.lock, self.conn:
            old = self.conn.execute('SELECT data,state FROM sends WHERE id=?', (identity,)).fetchone()
            if old:
                return False, {**json.loads(old['data']), 'status': old['state']}
            self.conn.execute('INSERT INTO sends VALUES(?,?,?,?,?)', (identity, customer_id, channel, 'sending', json.dumps(data, ensure_ascii=False)))
        return True, data

    def finish_send(self, identity, data):
        with self.lock, self.conn:
            self.conn.execute('UPDATE sends SET state=?,data=? WHERE id=?', (data['status'], json.dumps(data, ensure_ascii=False), identity))

    def recover_sends(self):
        with self.lock, self.conn:
            rows = self.conn.execute("SELECT * FROM sends WHERE state='sending'").fetchall()
            for row in rows:
                data = {**json.loads(row['data']), 'status': 'unknown', 'reason': '执行服务中断，发送结果未知；不会自动重发。'}
                self.conn.execute('UPDATE sends SET state=?,data=? WHERE id=?', ('unknown', json.dumps(data, ensure_ascii=False), row['id']))
                customer = self.get('customers', row['customer_id'])
                if customer:
                    messages = [x for x in customer.get('messages', []) if x['id'] != row['id']]
                    customer['messages'] = messages + [data]
                    self.put('customers', customer)

    def close(self):
        self.conn.close()
