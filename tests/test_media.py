import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
import media


def result(code,stdout=b'',stderr=b''):
    return SimpleNamespace(returncode=code,stdout=stdout,stderr=stderr)


def test_broken_probe_is_server_error_not_invalid_video(monkeypatch):
    monkeypatch.setattr(media.shutil,'which',lambda name:'/broken/ffprobe' if name=='ffprobe' else None)
    monkeypatch.setattr(media.platform,'system',lambda:'Linux')
    monkeypatch.setattr(media.subprocess,'run',lambda *args,**kwargs:result(-6,stderr=b'dyld: Library not loaded'))
    with pytest.raises(HTTPException) as error:
        media.probe_video('/tmp/input.mp4')
    assert error.value.status_code==503


def test_macos_native_probe_accepts_valid_h264_after_broken_ffprobe(monkeypatch,tmp_path):
    monkeypatch.setattr(media.shutil,'which',lambda name:'/bin/'+name)
    monkeypatch.setattr(media.platform,'system',lambda:'Darwin')
    monkeypatch.setattr(media.tempfile,'gettempdir',lambda:str(tmp_path))
    metadata={'streams':[{'codec_type':'video','codec_name':'h264','width':1280,'height':720}], 'format':{'duration':10}, 'playable':True}
    responses=iter([result(-6,stderr=b'Library not loaded'),result(0,stdout=json.dumps(metadata).encode())])
    monkeypatch.setattr(media.subprocess,'run',lambda *args,**kwargs:next(responses))
    data=b'\x00\x00\x00\x20ftyp' + b'mp42' + b'example'
    assert media.validate_media(data,'video/mp4',1920,1080)==data


def test_readable_probe_rejects_corrupt_file(monkeypatch):
    monkeypatch.setattr(media.shutil,'which',lambda name:'/bin/ffprobe')
    monkeypatch.setattr(media.subprocess,'run',lambda *args,**kwargs:result(1,stderr=b'moov atom not found'))
    with pytest.raises(HTTPException) as error:
        media.probe_video('/tmp/input.mp4')
    assert error.value.status_code==422
