"""Open a synthetic downloaded DOCX in Writer and check a persisted user edit."""
import json
import os
import sys
import time
import uno
from pathlib import Path
from com.sun.star.beans import PropertyValue
root=Path(sys.argv[1])
original=root/'original.docx';saved=root/'writer-edited.docx';pdf=root/'writer-edited.pdf'
local=uno.getComponentContext()
resolver=local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver',local)
for _ in range(100):
    try:
        ctx=resolver.resolve('uno:socket,host=127.0.0.1,port=20147;urp;StarOffice.ComponentContext');break
    except Exception:time.sleep(.15)
else:raise RuntimeError('Writer startup timeout')
desktop=ctx.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop',ctx)
def prop(name,value):
    v=PropertyValue();v.Name=name;v.Value=value;return v
uri=lambda p:uno.systemPathToFileUrl(str(p.resolve()))
def load(path):return desktop.loadComponentFromURL(uri(path),'_blank',0,(prop('Hidden',True),))
doc=load(original);assert doc is not None and doc.supportsService('com.sun.star.text.TextDocument')
before=doc.Text.String
assert all(before.count('Row %03d'%n)==1 for n in range(1,89))
c=doc.Text.createTextCursor();c.gotoEnd(False)
doc.Text.insertString(c,'\nWriter edit 089 已核对',False)
doc.storeAsURL(uri(saved),(prop('FilterName','Office Open XML Text'),prop('Overwrite',True)));doc.close(True)
r=load(saved);after=r.Text.String
assert after.count('Writer edit 089 已核对')==1
assert all(after.count('Row %03d'%n)==1 for n in range(1,89))
r.storeToURL(uri(pdf),(prop('FilterName','writer_pdf_Export'),prop('Overwrite',True)));r.close(True)
