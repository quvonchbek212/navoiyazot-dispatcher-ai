"""Durable single-host queue. Atomic claims/decisions; shared by API workers.

Lease heartbeats prevent duplicate work across uvicorn workers. A crashed
worker's job becomes interrupted, never silently replaying a decision.
"""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from fastapi.encoders import jsonable_encoder
from atil_ai_dispetcher.models import Settings

def encode(value):
    return json.dumps(jsonable_encoder(value), ensure_ascii=False, allow_nan=False)

class Store:
    def __init__(self, path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
              actor TEXT NOT NULL, created REAL NOT NULL, started REAL, finished REAL,
              stage TEXT NOT NULL, payload TEXT NOT NULL, result TEXT, error TEXT,
              dedupe TEXT UNIQUE, owner TEXT, heartbeat REAL);
            CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created DESC);
            CREATE TABLE IF NOT EXISTS decisions (
              job_id TEXT PRIMARY KEY REFERENCES jobs(id), decision TEXT NOT NULL,
              actor TEXT NOT NULL, note TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS notices (
              id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
              body TEXT NOT NULL, created REAL NOT NULL, read_at REAL, job_id TEXT);
            ''')
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path, timeout=15)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            with c: yield c
        finally: c.close()
    def settings(self):
        with self.db() as c: r=c.execute('SELECT body FROM settings WHERE id=1').fetchone()
        if not r:return Settings()
        raw=json.loads(r['body'])
        if raw.get('schema_version')!=2:
            raw={k:raw[k] for k in ('daily_time','monitor_minutes','analyze') if k in raw}
        return Settings.model_validate(raw)
    def migrate_v2(self):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT body FROM settings WHERE id=1').fetchone()
            raw=json.loads(row['body']) if row else {}
            if raw.get('schema_version')!=2:
                settings=Settings(**{k:raw[k] for k in ('daily_time','monitor_minutes','analyze') if k in raw})
                c.execute('INSERT INTO settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',(settings.model_dump_json(),))
                c.execute("UPDATE jobs SET status='interrupted',finished=?,error=?,stage='Arxivlangan' WHERE status IN ('queued','running')",
                          (time.time(),'Oldingi ish jarayoni o‘chirildi. Yangi dispetcher hisobidan foydalaning.'))
        self.prune(vacuum=True)

    def prune(self, *, keep_snapshots: int = 10, keep_other: int = 50, keep_rows: int = 200, vacuum: bool = False):
        """Bound SQLite size by dropping stale snapshot payloads while keeping recent and decided jobs."""
        changed = 0
        with self.db() as c:
            for scope, keep in (("kind IN ('snapshot','briefing')", keep_snapshots),
                                ("kind NOT IN ('snapshot','briefing')", keep_other)):
                changed += c.execute(f'''
                    UPDATE jobs SET result=NULL
                    WHERE {scope} AND result IS NOT NULL
                      AND status NOT IN ('queued','running')
                      AND id NOT IN (
                        SELECT id FROM jobs WHERE {scope} AND result IS NOT NULL
                        ORDER BY coalesce(finished, created) DESC, rowid DESC LIMIT ?
                      )
                      AND id NOT IN (SELECT job_id FROM decisions)
                ''', (keep,)).rowcount
            changed += c.execute('''
                DELETE FROM jobs
                WHERE actor='scheduler' AND status NOT IN ('queued','running')
                  AND id NOT IN (
                    SELECT id FROM jobs ORDER BY coalesce(finished, created) DESC, rowid DESC LIMIT ?
                  )
                  AND id NOT IN (SELECT job_id FROM decisions)
            ''', (keep_rows,)).rowcount
        if vacuum:
            conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
            try:
                freelist = conn.execute('PRAGMA freelist_count').fetchone()[0]
                if changed > 0 or freelist > 1000:
                    conn.execute('VACUUM')
            finally:
                conn.close()
    def save_settings(self, settings):
        with self.db() as c: c.execute('INSERT INTO settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',(settings.model_dump_json(),))
    def enqueue(self, payload, actor, dedupe=None):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if dedupe:
                row=c.execute('SELECT id FROM jobs WHERE dedupe=?',(dedupe,)).fetchone()
                if row: return row['id']
            if c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]>=20:
                raise ValueError('Navbat to‘lgan. Mavjud vazifalar tugashini kuting.')
            jid=uuid4().hex
            c.execute('INSERT INTO jobs(id,kind,status,actor,created,stage,payload,dedupe) VALUES(?,?,?,?,?,?,?,?)',
                      (jid,payload['kind'],'queued',actor,time.time(),'Navbatda',encode(payload),dedupe))
            return jid
    def schedule_briefing(self,payload,now,interval_minutes):
        """Retry a failed daily read after one monitor interval; preserve old attempts."""
        base=f'v2:daily:{now.date()}'
        with self.db() as c:
            row=c.execute('SELECT id,status,finished FROM jobs WHERE dedupe=? OR dedupe LIKE ? ORDER BY created DESC LIMIT 1',
                          (base,base+':retry:%')).fetchone()
        if row:
            if row['status'] not in ('failed','interrupted'):return row['id']
            if row['finished'] is None or now.timestamp()-row['finished']<interval_minutes*60:return row['id']
            bucket=int(now.timestamp())//(interval_minutes*60)
            return self.enqueue(payload,'scheduler',f'{base}:retry:{interval_minutes}:{bucket}')
        return self.enqueue(payload,'scheduler',base)

    def claim(self, owner):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute("UPDATE jobs SET status='interrupted',finished=?,error=?,stage='Uzilgan' WHERE status='running' AND heartbeat<?",
                      (time.time(),'Oldingi ishchi bilan aloqa uzilgan; qayta ishga tushiring.',time.time()-120))
            if c.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone(): return None
            r=c.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not r:return None
            c.execute("UPDATE jobs SET status='running',started=?,heartbeat=?,owner=?,stage='Hisoblanmoqda' WHERE id=?",(time.time(),time.time(),owner,r['id']))
        return self.job(r['id'])
    def beat(self, jid, owner):
        with self.db() as c:c.execute("UPDATE jobs SET heartbeat=? WHERE id=? AND owner=? AND status='running'",(time.time(),jid,owner))
    def stage(self,jid,stage):
        with self.db() as c:c.execute('UPDATE jobs SET stage=? WHERE id=?',(stage,jid))
    def finish(self,jid,owner,result=None,error=None):
        with self.db() as c:
            c.execute("UPDATE jobs SET status=?,stage=?,finished=?,result=?,error=? WHERE id=? AND owner=? AND status='running'",
                      ('failed' if error else 'complete','Xato' if error else 'Tayyor',time.time(),encode(result) if result is not None else None,error,jid,owner))
        if result is not None:
            self.prune(vacuum=False)
    def _row(self,r,full=True):
        if not r:return None
        d=dict(r)
        for key in ('payload','result'):
            if key in d: d[key]=json.loads(d[key]) if d[key] else None
        d.pop('owner',None); d.pop('heartbeat',None); d.pop('dedupe',None)
        return d
    def job(self,jid):
        with self.db() as c:
            r=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
            decision=c.execute('SELECT * FROM decisions WHERE job_id=?',(jid,)).fetchone()
        d=self._row(r)
        if d:d['decision']=dict(decision) if decision else None
        return d
    def jobs(self,limit=50):
        with self.db() as c:r=c.execute('SELECT id,kind,status,actor,created,started,finished,stage,error FROM jobs ORDER BY created DESC LIMIT ?',(limit,)).fetchall()
        return [dict(x) for x in r]
    def latest_snapshot(self):
        with self.db() as c:r=c.execute("SELECT id,result,finished FROM jobs WHERE kind IN ('snapshot','briefing') AND status='complete' AND json_extract(result,'$.contract_version')=2 ORDER BY finished DESC LIMIT 1").fetchone()
        if not r:return None
        data=json.loads(r['result'])
        return {'job_id':r['id'],'finished':r['finished'],'data':data.get('snapshot',data)}
    def latest_briefing(self):
        with self.db() as c:r=c.execute("SELECT id,result,finished FROM jobs WHERE kind='briefing' AND status='complete' AND json_extract(result,'$.contract_version')=2 ORDER BY finished DESC LIMIT 1").fetchone()
        return {'job_id':r['id'],'finished':r['finished'],'data':json.loads(r['result'])} if r else None
    def decide(self,jid,decision,actor,note):
        with self.db() as c:
            try:c.execute('INSERT INTO decisions VALUES(?,?,?,?,?)',(jid,decision,actor,note,time.time()))
            except sqlite3.IntegrityError:raise ValueError('Bu reja bo‘yicha qaror allaqachon qayd etilgan.')
        return self.job(jid)['decision']
    def notice(self,fingerprint,title,body,jid):
        with self.db() as c:c.execute('INSERT OR IGNORE INTO notices(id,fingerprint,title,body,created,job_id) VALUES(?,?,?,?,?,?)',(uuid4().hex,fingerprint,title,body,time.time(),jid))
    def notices(self):
        with self.db() as c:return [dict(r) for r in c.execute('SELECT * FROM notices ORDER BY created DESC LIMIT 100')]
    def read_notice(self,nid):
        with self.db() as c:return c.execute('UPDATE notices SET read_at=coalesce(read_at,?) WHERE id=?',(time.time(),nid)).rowcount
