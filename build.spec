# -*- mode: python ; coding: utf-8 -*-
import os
block_cipher = None
datas = [('static','static'),('seed.json','.')]
if os.path.exists('cert.pem'): datas.append(('cert.pem','.'))
if os.path.exists('key.pem'):  datas.append(('key.pem','.'))
a = Analysis(['main.py'], pathex=['.'], binaries=[], datas=datas,
    hiddenimports=['flask','werkzeug','werkzeug.serving','werkzeug.routing',
        'jinja2','click','itsdangerous','blinker','sqlite3','_sqlite3',
        'OpenSSL','OpenSSL.SSL','OpenSSL.crypto','cryptography',
        'cryptography.hazmat.primitives','cryptography.hazmat.backends',
        'tkinter','tkinter.messagebox','tkinter.ttk','email','email.mime','email.mime.text'],
    hookspath=[], runtime_hooks=[], excludes=['matplotlib','numpy','pandas','PIL'],
    win_no_prefer_redirects=False, win_private_assemblies=False,
    cipher=block_cipher, noarchive=False)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='InventarioQR', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, upx_exclude=[], runtime_tmpdir=None, console=False, icon=None)
