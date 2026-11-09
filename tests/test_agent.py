# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import os, sys, json, tempfile, shutil, unittest, logging
sys.path.insert(0,os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'src'))
from trassir_agent.core import CollectorApplication,SenderApplication
class Transport(object):
    def __init__(self,status): self.status=status; self.payloads=[]
    def send(self,payload,c,resolve):
        self.payloads.append(payload)
        if isinstance(self.status,Exception): raise self.status
        return self.status
class AgentTests(unittest.TestCase):
    def setUp(self):
        self.root=tempfile.mkdtemp(); self.path=os.path.join(self.root,'config.json'); self.apps=[]
        source=os.path.join(os.path.dirname(os.path.dirname(__file__)),'config','config.example.json')
        with open(source) as f: self.c=json.load(f)
        self.c['sender']['enabled']=True; self.c['collector']['heartbeat_seconds']=0
        with open(self.path,'w') as f: json.dump(self.c,f)
        self.collector=CollectorApplication(self.path); self.apps.append(self.collector)
    def tearDown(self):
        for app in self.apps: app.repository.db.close()
        for role in ('collector','sender'):
            logger=logging.getLogger('trassir_agent.'+role)
            for h in list(logger.handlers): h.close(); logger.removeHandler(h)
        shutil.rmtree(self.root)
    def event(self):
        self.collector.save(self.collector.factory.create('trassir.system_event',{'type':'test'}))
    def sender(self,status):
        app=SenderApplication(self.path,Transport(status)); self.apps.append(app); return app
    def test_200(self):
        self.event(); app=self.sender(200); app.tick()
        self.assertEqual(app.repository.db.execute('SELECT status FROM events').fetchone()[0],'delivered')
    def test_204(self):
        self.event(); app=self.sender(204); app.tick()
        self.assertEqual(app.repository.db.execute('SELECT status FROM batches').fetchone()[0],'pending')
    def test_retry(self):
        self.event(); app=self.sender(500); app.tick()
        with app.repository.db: app.repository.db.execute('UPDATE batches SET next_at=0')
        app.transport.status=200; app.tick()
        self.assertEqual(app.transport.payloads[0],app.transport.payloads[1])
    def test_network(self):
        self.event(); app=self.sender(IOError('offline')); app.tick()
        self.assertEqual(app.repository.db.execute('SELECT attempts FROM batches').fetchone()[0],1)
    def test_archive_failure(self):
        def fail(e): raise IOError('disk')
        self.collector.writer.append=fail; self.event()
        self.assertEqual(self.collector.repository.db.execute('SELECT count(*) FROM events').fetchone()[0],1)
    def test_db_failure(self):
        self.collector.repository.db.close(); output=[]; self.collector.writer.append=output.append
        with self.assertRaises(Exception): self.event()
        self.assertEqual(output,[])
    def test_reload(self):
        with open(self.path,'w') as f: f.write('{')
        self.collector.config.next_check=0; self.collector.refresh()
        self.assertIsNotNone(self.collector.config.error)
        self.assertEqual(self.collector.config.value['server_id'],'video81')
    def test_log_checkpoint(self):
        path=os.path.join(self.root,'input.log')
        with open(path,'wb') as f: f.write(b'first\nsecond\n')
        src={'id':'input','path':path,'start_at':'start'}
        self.collector.collect_log(src); self.collector.collect_log(src)
        self.assertEqual(self.collector.repository.db.execute('SELECT count(*) FROM events').fetchone()[0],2)
    def test_lease(self):
        self.event(); a=self.sender(200); b=self.sender(200)
        self.assertIsNotNone(a.repository.claim(a.config.value,a.owner))
        self.assertIsNone(b.repository.claim(b.config.value,b.owner))
if __name__=='__main__': unittest.main()
