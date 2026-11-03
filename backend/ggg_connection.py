"""Write-only web-session credentials, isolated from league data and public APIs."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3,time,uuid,re


class ConnectionError(ValueError):pass


class GGGConnectionStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path.touch(mode=0o600,exist_ok=True);self.path.chmod(0o600)
        with self.connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS connection(
             singleton INTEGER PRIMARY KEY CHECK(singleton=1),guild_id TEXT NOT NULL,session_id TEXT NOT NULL,
             source_id INTEGER,enabled INTEGER NOT NULL,revision TEXT NOT NULL,state TEXT NOT NULL,
             error_code TEXT,checked_at REAL,next_request REAL NOT NULL DEFAULT 0,pages INTEGER NOT NULL DEFAULT 0);
             INSERT OR IGNORE INTO connection VALUES(1,'','',NULL,0,'unconfigured','unconfigured',NULL,NULL,0,0);''')
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=5);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    def get(self):
        with self.connect() as c:return dict(c.execute('SELECT * FROM connection WHERE singleton=1').fetchone())
    def public(self):
        row=self.get()
        return {k:row[k] for k in ('guild_id','source_id','enabled','revision','state','error_code','checked_at','next_request','pages')}|{'session_configured':bool(row['session_id'])}
    def save(self,guild_id,session_id,source_id,enabled,clear=False):
        old=self.get()
        if not isinstance(guild_id,str) or not re.fullmatch(r'[1-9][0-9]{0,19}',guild_id):raise ConnectionError('invalid_guild_id')
        if not isinstance(session_id,str):raise ConnectionError('invalid_session_id')
        session_id=session_id.strip()
        if session_id.startswith('POESESSID='):session_id=session_id[len('POESESSID='):].removesuffix(';')
        if session_id and not re.fullmatch(r'[A-Za-z0-9_-]{16,256}',session_id):raise ConnectionError('invalid_session_id')
        secret='' if clear else session_id or old['session_id']
        if enabled and not secret:raise ConnectionError('session_required')
        if type(enabled) is not bool or type(clear) is not bool:raise ConnectionError('invalid_connection')
        revision=str(uuid.uuid4())
        with self.connect() as c:c.execute("UPDATE connection SET guild_id=?,session_id=?,source_id=?,enabled=?,revision=?,state=?,error_code=NULL,checked_at=NULL,pages=0 WHERE singleton=1",(guild_id,secret,source_id,int(enabled),revision,'unknown' if enabled else 'disabled'))
        return self.public()
    def mark(self,revision,state,error=None,pages=None):
        with self.connect() as c:c.execute('UPDATE connection SET state=?,error_code=?,checked_at=?,pages=COALESCE(?,pages) WHERE singleton=1 AND revision=?',(state,error,time.time(),pages,revision))
    def cooldown(self,until):
        with self.connect() as c:c.execute('UPDATE connection SET next_request=MAX(next_request,?) WHERE singleton=1',(until,))
