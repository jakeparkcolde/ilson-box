"""Pillow가 없는 맥의 사진 정규화. ImageIO 검증 + sips 변환."""
import ctypes
import os
from pathlib import Path
import subprocess
import tempfile
from inbox_files import InboxError
import inbox_files


def metadata(raw):
    c = ctypes
    try:
        cf = c.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        io = c.CDLL('/System/Library/Frameworks/ImageIO.framework/ImageIO')
        ptr = c.c_void_p
        cf.CFDataCreate.argtypes=[ptr,ptr,c.c_long]; cf.CFDataCreate.restype=ptr
        io.CGImageSourceCreateWithData.argtypes=[ptr,ptr]; io.CGImageSourceCreateWithData.restype=ptr
        io.CGImageSourceGetCount.argtypes=[ptr]; io.CGImageSourceGetCount.restype=c.c_size_t
        io.CGImageSourceCopyPropertiesAtIndex.argtypes=[ptr,c.c_size_t,ptr]; io.CGImageSourceCopyPropertiesAtIndex.restype=ptr
        cf.CFDictionaryGetValue.argtypes=[ptr,ptr]; cf.CFDictionaryGetValue.restype=ptr
        cf.CFNumberGetValue.argtypes=[ptr,c.c_int,ptr]; cf.CFNumberGetValue.restype=c.c_bool
        cf.CFRelease.argtypes=[ptr]
        data=cf.CFDataCreate(None,raw,len(raw)); source=None; props=None
        if not data: raise ValueError()
        try:
            source=io.CGImageSourceCreateWithData(data,None)
            if not source or io.CGImageSourceGetCount(source)!=1: raise ValueError()
            props=io.CGImageSourceCopyPropertiesAtIndex(source,0,None)
            if not props: raise ValueError()
            values=[]
            for key in ('kCGImagePropertyPixelWidth','kCGImagePropertyPixelHeight','kCGImagePropertyOrientation'):
                value=cf.CFDictionaryGetValue(props,ptr.in_dll(io,key)); number=c.c_longlong()
                if value and not cf.CFNumberGetValue(value,4,c.byref(number)): raise ValueError()
                values.append(number.value)
            width,height,orientation=values
            if width<1 or height<1 or width*height>inbox_files.MAX_PIXELS or orientation not in range(9): raise ValueError()
            return width,height,orientation or 1
        finally:
            if props: cf.CFRelease(props)
            if source: cf.CFRelease(source)
            cf.CFRelease(data)
    except (OSError,ValueError,AttributeError):
        raise InboxError('사진 크기와 방향을 확인하지 못했습니다.') from None


def strip_metadata(raw):
    # sips가 만든 JPEG에서 APP1~APP15 및 주석을 제거한다.
    if not raw.startswith(b'\xff\xd8'): raise InboxError('변환한 사진을 읽지 못했습니다.')
    out=bytearray(raw[:2]); pos=2
    while pos+4 <= len(raw):
        if raw[pos] != 0xff: raise InboxError('변환한 사진을 읽지 못했습니다.')
        marker=raw[pos+1]
        if marker == 0xda:
            out.extend(raw[pos:]); return bytes(out)
        length=int.from_bytes(raw[pos+2:pos+4],'big')
        end=pos+2+length
        if length<2 or end>len(raw): raise InboxError('변환한 사진을 읽지 못했습니다.')
        if not (0xe1<=marker<=0xef or marker==0xfe): out.extend(raw[pos:end])
        pos=end
    raise InboxError('변환한 사진을 읽지 못했습니다.')


def normalize_sips(name, raw):
    width,height,orientation=metadata(raw)
    expected={'.jpg':'jpeg','.jpeg':'jpeg','.png':'png','.heic':'heic'}.get(Path(name).suffix.lower())
    if not expected: raise InboxError('지원하지 않는 파일입니다.')
    try:
        # 난수 임시 폴더와 0600 파일. 정상 종료 시 삭제되며 비정상 종료 시 남을 수 있다.
        with tempfile.TemporaryDirectory(prefix='ilson-inbox-') as directory:
            source=Path(directory)/'source'; output=Path(directory)/'result.jpg'
            fd=os.open(str(source),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f:f.write(raw)
            result=subprocess.run(['/usr/bin/sips','-g','format',str(source)],capture_output=True,text=True,timeout=20)
            if result.returncode or ('format: '+expected) != result.stdout.splitlines()[-1].strip(): raise ValueError()
            transform={1:[],2:['-f','horizontal'],3:['-r','180'],4:['-f','vertical'],
                       5:['-r','90','-f','vertical'],6:['-r','90'],
                       7:['-r','90','-f','horizontal'],8:['-r','270']}[orientation]
            for edge in (1600,1280,1024,800):
                for quality in (88,72,55):
                    args=['/usr/bin/sips'] + (['-Z',str(edge)] if max(width,height)>edge else []) + transform
                    args += ['-s','format','jpeg','-s','formatOptions',str(quality),str(source),'-o',str(output)]
                    result=subprocess.run(args,capture_output=True,timeout=30)
                    if result.returncode or not output.is_file(): raise ValueError()
                    image=strip_metadata(output.read_bytes())
                    if len(image)<=240000:return image
    except (OSError,ValueError,subprocess.TimeoutExpired,IndexError):
        raise InboxError('사진을 변환하지 못했습니다.') from None
    raise InboxError('사진이 너무 복잡해 준비하지 못했습니다.')
