# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import os, json, time, uuid, sqlite3, ssl, logging, random
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
try:
    import httplib
    from urlparse import urlsplit
    from urllib import urlencode
    STRING = basestring
except ImportError:
    import http.client as httplib
    from urllib.parse import urlsplit, urlencode
    STRING = str

def utc():
    return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]+'Z'
def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
def mkdir(path):
    if path and not os.path.isdir(path):
        try: os.makedirs(path)
        except OSError:
            if not os.path.isdir(path): raise
def scalar(value):
    if value is None or isinstance(value, (bool, int, float)): return value
    if isinstance(value, bytes): return value.decode('utf-8', 'replace')
    try: return unicode(value)
    except NameError: return str(value)

def validate_url(value):
    u=urlsplit(value)
    if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.fragment:
        raise ValueError('HTTP or HTTPS URL required')
    if u.port is not None and not 1 <= u.port <= 65535:
        raise ValueError('Invalid port')
    return u

class ConfigManager(object):
    def __init__(self, path):
        self.path=os.path.abspath(path); self.base=os.path.dirname(self.path)
        self.value=None; self.next_check=0; self.error=None
        self.reload()
    def resolve(self, path):
        return path if os.path.isabs(path) else os.path.join(self.base, path)
    def reload(self):
        if time.time()<self.next_check: return
        self.next_check=time.time()+5
        try:
            with open(self.path, 'rb') as f: c=json.loads(f.read().decode('utf-8-sig'))
            self.validate(c)
            self.value=c; self.error=None
        except Exception as e:
            self.error=scalar(e)
            if self.value is None: raise
    def validate(self, c):
        if c['config_version']!=1 or not isinstance(c['server_id'], STRING) or not c['server_id']: raise ValueError('Invalid config identity')
        d=c['delivery']; s=c['sender']; k=c['collector']
        if d['contract_version']!='1.0': raise ValueError('Unsupported contract')
        validate_url(d['url'])
        if d.get('auth_file') and d.get('token_file'): raise ValueError('Choose auth_file or token_file')
        if d.get('auth_file') and not isinstance(d['auth_file'], STRING): raise ValueError('Invalid auth_file')
        for section in (s,k):
            if not isinstance(section['enabled'],bool): raise ValueError('enabled must be boolean')
            if type(section['tick_seconds']) is not int or not 1<=section['tick_seconds']<=3600: raise ValueError('Invalid tick')
        for value,lo,hi in ((s['batch_size'],1,1000),(s['max_batch_bytes'],1024,4194304),(d['timeout_seconds'],1,60),(s['retry_initial_seconds'],1,3600),(s['retry_max_seconds'],1,86400),(s['retention_days'],0,3650)):
            if type(value) is not int or not lo<=value<=hi: raise ValueError('Invalid numeric setting')
        if s['retry_initial_seconds']>s['retry_max_seconds']: raise ValueError('Invalid retry range')
        if not isinstance(k['file_copy_enabled'],bool): raise ValueError('Invalid file_copy_enabled')
        if not isinstance(k['exclude_event_types'],list): raise ValueError('Invalid filters')
        if type(k['heartbeat_seconds']) is not int or not 0<=k['heartbeat_seconds']<=86400: raise ValueError('Invalid heartbeat')
        ids=set()
        for source in k['log_sources']:
            if not source['id'] or source['id'] in ids: raise ValueError('Invalid source id')
            ids.add(source['id'])
            if source.get('start_at','end') not in ('start','end'): raise ValueError('Invalid start_at')
            ''.encode(source.get('encoding','utf-8'))
            if not source['path']: raise ValueError('Missing log path')
        for key in ('database','archive','logs'):
            if not c['storage'][key]: raise ValueError('Missing storage path')
        if self.value:
            if c['storage']!=self.value['storage'] or c['server_id']!=self.value['server_id']: raise ValueError('Restart required for storage/identity')
            if any(d[x]!=self.value['delivery'][x] for x in ('url','destination_id')): raise ValueError('Explicit destination migration required')

class EventRepository(object):
    def __init__(self,path,c):
        self._database_path = path
        self._thread_local = threading.local()
        mkdir(os.path.dirname(path))
        self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.executescript("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v TEXT); CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,payload TEXT,created REAL,status TEXT DEFAULT 'pending',batch_id TEXT); CREATE INDEX IF NOT EXISTS ready ON events(status); CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,payload TEXT,status TEXT,attempts INTEGER DEFAULT 0,next_at REAL DEFAULT 0,lease REAL DEFAULT 0,owner TEXT,error TEXT,created REAL,delivered REAL); CREATE TABLE IF NOT EXISTS offsets(id TEXT PRIMARY KEY,state TEXT);")
        identity=dumps([c['server_id'],c['delivery']['destination_id'],c['delivery']['url']])
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('schema','1')")
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('identity',?)",(identity,))
        if self.db.execute("SELECT v FROM meta WHERE k='schema'").fetchone()[0]!='1': raise ValueError('Unknown database schema')
        if self.db.execute("SELECT v FROM meta WHERE k='identity'").fetchone()[0]!=identity: raise ValueError('Database identity mismatch')
    @property
    def db(self):
        connection = getattr(self._thread_local, 'connection', None)
        if connection is None:
            connection = sqlite3.connect(self._database_path, timeout=5)
            try:
                connection.row_factory = sqlite3.Row
                connection.execute('PRAGMA synchronous=NORMAL')
            except Exception:
                connection.close()
                raise
            self._thread_local.connection = connection
        return connection
    def save(self,event,checkpoint=None):
        with self.db:
            self.db.execute('INSERT INTO events(id,payload,created) VALUES(?,?,?)',(event['event_id'],dumps(event),time.time()))
            if checkpoint: self.db.execute('INSERT OR REPLACE INTO offsets VALUES(?,?)',checkpoint)
    def offset(self,key):
        row=self.db.execute('SELECT state FROM offsets WHERE id=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None
    def checkpoint(self,key,state):
        with self.db: self.db.execute('INSERT OR REPLACE INTO offsets VALUES(?,?)',(key,dumps(state)))
    def claim(self,c,owner):
        t=time.time()
        try:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.db.execute("SELECT * FROM batches WHERE status='pending' ORDER BY created LIMIT 1").fetchone()
            if row and (row[5]>t or row[4]>t): self.db.rollback(); return None
            if not row:
                rows=self.db.execute("SELECT * FROM events WHERE status='pending' ORDER BY created LIMIT ?",(c['sender']['batch_size'],)).fetchall()
                batch={'contract':'trassir.telemetry','contract_version':'1.0','batch_id':str(uuid.uuid4()),'sent_at':utc(),'producer':{'name':'trassir-sdk-agent','version':'1.0.0'},'server':{'server_id':c['server_id']},'events':[]}
                selected=[]
                for event in rows:
                    batch['events'].append(json.loads(event[1]))
                    if len(dumps(batch).encode('utf-8'))>c['sender']['max_batch_bytes']:
                        batch['events'].pop()
                        if not selected:
                            self.db.execute("UPDATE events SET status='quarantine' WHERE id=?",(event[0],)); continue
                        break
                    selected.append(event[0])
                if not selected: self.db.commit(); return None
                self.db.execute("INSERT INTO batches(id,payload,status,created) VALUES(?,?,'pending',?)",(batch['batch_id'],dumps(batch),t))
                self.db.executemany("UPDATE events SET status='batched',batch_id=? WHERE id=?",[(batch['batch_id'],eid) for eid in selected])
                row=self.db.execute('SELECT * FROM batches WHERE id=?',(batch['batch_id'],)).fetchone()
            self.db.execute('UPDATE batches SET lease=?,owner=? WHERE id=?',(t+max(120,c['delivery']['timeout_seconds']*20),owner,row[0]))
            self.db.commit(); return {'id':row[0],'payload':row[1]}
        except Exception: self.db.rollback(); raise
    def finish(self,bid,owner,ok,error,c):
        with self.db:
            row=self.db.execute('SELECT * FROM batches WHERE id=? AND owner=?',(bid,owner)).fetchone()
            if not row: return
            if ok:
                self.db.execute("UPDATE batches SET status='delivered',delivered=?,lease=0,owner=NULL,error=NULL WHERE id=?",(time.time(),bid))
                self.db.execute("UPDATE events SET status='delivered' WHERE batch_id=?",(bid,))
            else:
                n=row[3]+1; s=c['sender']
                delay=min(s['retry_max_seconds'],s['retry_initial_seconds']*2**min(n-1,16))*random.uniform(0.8,1.2)
                self.db.execute('UPDATE batches SET attempts=?,next_at=?,lease=0,owner=NULL,error=? WHERE id=?',(n,time.time()+delay,error,bid))
    def cleanup(self,days):
        if not days: return
        with self.db:
            rows=self.db.execute("SELECT id FROM batches WHERE status='delivered' AND delivered<? LIMIT 100",(time.time()-days*86400,)).fetchall()
            for row in rows:
                self.db.execute('DELETE FROM events WHERE batch_id=?',(row[0],)); self.db.execute('DELETE FROM batches WHERE id=?',(row[0],))

class EventFactory(object):
    def create(self,kind,data,source=None):
        return {'event_id':str(uuid.uuid4()),'event_type':kind,'event_version':'1.0','occurred_at':None,'observed_at':utc(),'source':source or {},'data':data}
    def from_sdk(self,ev):
        data={key:scalar(getattr(ev,key,None)) for key in ('type','p1','p2','p3')}
        data['timestamp_raw']=scalar(getattr(ev,'ts',None))
        return self.create('trassir.system_event',data,{'object_id':scalar(getattr(ev,'origin',None)),'object_name':scalar(getattr(getattr(ev,'origin_object',None),'name',None))})

class EventFileWriter(object):
    def __init__(self,path): self.path=path
    def append(self,event):
        mkdir(os.path.dirname(self.path)); data=(dumps({'record_version':1,'event':event})+'\n').encode('utf-8')
        if os.path.exists(self.path) and os.path.getsize(self.path)+len(data)>10485760:
            for i in range(3,0,-1):
                src=self.path if i==1 else self.path+'.'+str(i-1); dst=self.path+'.'+str(i)
                if os.path.exists(dst): os.remove(dst)
                if os.path.exists(src): os.rename(src,dst)
        with open(self.path,'ab') as f: f.write(data)

class Application(object):
    def __init__(self,path,role):
        self.config=ConfigManager(path); c=self.config.value
        directory=self.config.resolve(c['storage']['logs']); mkdir(directory)
        self.logger=logging.getLogger('trassir_agent.'+role); self.logger.propagate=False
        if not self.logger.handlers:
            handler=RotatingFileHandler(os.path.join(directory,role+'.log'),maxBytes=2097152,backupCount=3,encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s')); self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO); self.last_error=None
        self.repository=EventRepository(self.config.resolve(c['storage']['database']),c)
    def refresh(self):
        self.config.reload()
        if self.config.error!=self.last_error:
            if self.config.error: self.logger.error('Config rejected: %s',self.config.error)
            self.last_error=self.config.error
        self.logger.setLevel(getattr(logging,self.config.value.get('log_level','INFO'),logging.INFO))
        return self.config.value

class CollectorApplication(Application):
    def __init__(self,path):
        Application.__init__(self,path,'collector'); self.factory=EventFactory()
        self.writer=EventFileWriter(self.config.resolve(self.config.value['storage']['archive']))
        self.warning_at=0; self.heartbeat_at=0
    def save(self,event,checkpoint=None):
        self.repository.save(event,checkpoint)
        if self.config.value['collector']['file_copy_enabled']:
            try: self.writer.append(event)
            except Exception:
                if time.time()>=self.warning_at:
                    self.logger.warning('File copy failed; no retry',exc_info=True); self.warning_at=time.time()+60
    def on_event(self,ev):
        try:
            c=self.refresh()
            if not c['collector']['enabled']: return
            event=self.factory.from_sdk(ev)
            if event['data']['type'] not in c['collector']['exclude_event_types']: self.save(event)
        except Exception: self.logger.exception('Event NOT saved')
    def collect_log(self,source):
        path=self.config.resolve(source['path']); canonical=os.path.normcase(os.path.realpath(path))
        logs=os.path.normcase(os.path.realpath(self.config.resolve(self.config.value['storage']['logs'])))
        archive=os.path.normcase(os.path.realpath(self.writer.path))
        if canonical.startswith(logs+os.sep) or canonical==archive or canonical.startswith(archive+'.'): raise ValueError('Agent output cannot be input')
        st=os.stat(path); identity='%s:%s'%(st.st_dev,st.st_ino); state=self.repository.offset(source['id'])
        if state is None: state={'identity':identity,'position':st.st_size if source.get('start_at','end')=='end' else 0}
        elif state['identity']!=identity or state['position']>st.st_size: state={'identity':identity,'position':0}
        with open(path,'rb') as f:
            f.seek(state['position'])
            for unused in range(100):
                line=f.readline(65536)
                if not line: break
                if not line.endswith(b'\n') and len(line)<65536: break
                event=self.factory.create('trassir.log_entry',{'source_id':source['id'],'level':None,'message':line.decode(source.get('encoding','utf-8'),'replace').rstrip('\r\n'),'chunked':not line.endswith(b'\n')})
                state={'identity':identity,'position':f.tell()}; self.save(event,(source['id'],dumps(state)))
        self.repository.checkpoint(source['id'],state)
    def tick(self):
        c=self.refresh()
        if not c['collector']['enabled']: return
        for source in c['collector']['log_sources']:
            try: self.collect_log(source)
            except Exception: self.logger.exception('Log collection failed: %s',source['id'])
        interval=c['collector']['heartbeat_seconds']
        if interval and time.time()>=self.heartbeat_at:
            self.save(self.factory.create('agent.heartbeat',{'component':'collector'})); self.heartbeat_at=time.time()+interval

class PulseAuthError(Exception):
    pass

class HttpTransport(object):
    def _post(self,url,payload,headers,c,resolve,read_body=False):
        u=validate_url(url)
        if u.scheme=='https':
            context=ssl.create_default_context(cafile=resolve(c['ca_file']) if c.get('ca_file') else None)
            conn=httplib.HTTPSConnection(u.hostname,u.port or 443,timeout=c['timeout_seconds'],context=context)
        else:
            conn=httplib.HTTPConnection(u.hostname,u.port or 80,timeout=c['timeout_seconds'])
        try:
            conn.request('POST',(u.path or '/')+('?' + u.query if u.query else ''),payload,headers)
            response=conn.getresponse()
            status=response.status
            if read_body:
                logging.getLogger('trassir_agent.sender').info('PULSE_AUTH HTTP %s',status)
                if not 200<=status<300: raise PulseAuthError('Token endpoint HTTP %s'%status)
                body=response.read(1048577)
                if len(body)>1048576: raise PulseAuthError('Token response too large')
                return body
            return status
        finally:
            conn.close()
    def _token(self,value):
        if not isinstance(value,STRING): raise ValueError('Token must be a string')
        value=value.strip()
        if not value or '\r' in value or '\n' in value: raise ValueError('Empty or invalid token')
        value.encode('ascii')
        return value
    def _get_token(self,c,resolve):
        with open(resolve(c['auth_file']),'rb') as f:
            auth=json.loads(f.read().decode('utf-8-sig'))
        fmt=auth['request_format']; path=auth['token_path']; body=auth['body']
        if not isinstance(path,list) or not path or not all(isinstance(key,STRING) for key in path):
            raise ValueError('token_path must be a non-empty list of keys')
        headers={'Accept':'application/json'}
        if fmt=='json':
            payload=json.dumps(body,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
            headers['Content-Type']='application/json; charset=utf-8'
        elif fmt=='form':
            if not isinstance(body,dict): raise ValueError('Form body must be an object')
            fields=[]
            for key,value in body.items():
                values=value if isinstance(value,(list,tuple)) else [value]
                for item in values:
                    fields.append((scalar(key).encode('utf-8'),scalar(item).encode('utf-8')))
            payload=urlencode(fields).encode('ascii')
            headers['Content-Type']='application/x-www-form-urlencoded'
        else:
            raise ValueError('request_format must be json or form')
        if auth.get('token_url'):
            url=auth['token_url']
        else:
            u=validate_url(c['url'])
            url=u.scheme+'://'+u.netloc+'/pulse-platform/api/v1/auth/token'
        value=json.loads(self._post(url,payload,headers,c,resolve,True).decode('utf-8-sig'))
        for key in path: value=value[key]
        return self._token(value)
    def send(self,payload,c,resolve):
        headers={'Content-Type':'application/json; charset=utf-8','User-Agent':'trassir-sdk-agent/1.0.0'}
        if c.get('auth_file'):
            token=self._get_token(c,resolve)
            headers['Authorization']='Bearer '+token
        elif c.get('token_file'):
            with open(resolve(c['token_file']),'rb') as f: token=self._token(f.read().decode('ascii'))
            headers['Authorization']='Bearer '+token
        return self._post(c['url'],payload.encode('utf-8'),headers,c,resolve)

class SenderApplication(Application):
    def __init__(self,path,transport=None):
        Application.__init__(self,path,'sender'); self.transport=transport or HttpTransport()
        self.owner=str(uuid.uuid4()); self.cleanup_at=0
    def tick(self):
        c=self.refresh()
        if not c['sender']['enabled']: return
        batch=self.repository.claim(c,self.owner)
        if batch:
            ok=False; error=None
            try:
                status=self.transport.send(batch['payload'],c['delivery'],self.config.resolve)
                ok=status==200; error=None if ok else 'HTTP %s'%status
            except PulseAuthError as e: error=scalar(e)
            except Exception as e: error=type(e).__name__
            self.repository.finish(batch['id'],self.owner,ok,error,c)
            if ok: self.logger.info('Delivered batch=%s',batch['id'])
            else: self.logger.warning('Failed batch=%s error=%s',batch['id'],error)
        if time.time()>=self.cleanup_at:
            self.repository.cleanup(c['sender']['retention_days']); self.cleanup_at=time.time()+3600
