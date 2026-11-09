# -*- coding: utf-8 -*-
from __future__ import print_function
import os, hashlib, zipfile
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT,'VERSION')) as f: version=f.read().strip()
out=os.path.join(ROOT,'dist')
if not os.path.isdir(out): os.makedirs(out)
path=os.path.join(out,'trassir-sdk-agent-'+version+'.zip')
allowed=['src/trassir_agent/__init__.py','src/trassir_agent/core.py','scripts/collector.py','scripts/sender.py','config/config.example.json','docs/OPERATIONS.md','README.md','VERSION']
with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
    for name in allowed:
        z.write(os.path.join(ROOT,*name.split('/')),name)
with open(path,'rb') as f: digest=hashlib.sha256(f.read()).hexdigest()
with open(path+'.sha256','w') as f: f.write(digest+'  '+os.path.basename(path)+'\n')
print(path)
