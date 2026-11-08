"""macOS PDF 검사: 5MB, 10쪽, 암호화되지 않은 문서만 허용한다."""
import ctypes
import subprocess
import sys

MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 10

def _page_count(raw):
    c=ctypes; ptr=c.c_void_p
    cf=c.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    cg=c.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    cf.CFDataCreate.argtypes=[ptr,ptr,c.c_long];cf.CFDataCreate.restype=ptr
    cg.CGDataProviderCreateWithCFData.argtypes=[ptr];cg.CGDataProviderCreateWithCFData.restype=ptr
    cg.CGPDFDocumentCreateWithProvider.argtypes=[ptr];cg.CGPDFDocumentCreateWithProvider.restype=ptr
    cg.CGPDFDocumentGetNumberOfPages.argtypes=[ptr];cg.CGPDFDocumentGetNumberOfPages.restype=c.c_size_t
    cg.CGPDFDocumentIsEncrypted.argtypes=[ptr];cg.CGPDFDocumentIsEncrypted.restype=c.c_bool
    cg.CGPDFDocumentRelease.argtypes=[ptr];cg.CGDataProviderRelease.argtypes=[ptr];cf.CFRelease.argtypes=[ptr]
    data=cf.CFDataCreate(None,raw,len(raw));provider=None;doc=None
    if not data:raise ValueError()
    try:
        provider=cg.CGDataProviderCreateWithCFData(data)
        if not provider:raise ValueError()
        doc=cg.CGPDFDocumentCreateWithProvider(provider)
        if not doc or cg.CGPDFDocumentIsEncrypted(doc):raise ValueError()
        pages=cg.CGPDFDocumentGetNumberOfPages(doc)
        if not 1<=pages<=MAX_PDF_PAGES:raise ValueError()
        return pages
    finally:
        if doc:cg.CGPDFDocumentRelease(doc)
        if provider:cg.CGDataProviderRelease(provider)
        cf.CFRelease(data)

def validate_pdf(raw):
    from inbox_files import InboxError
    if not raw.startswith(b'%PDF-') or len(raw)>MAX_PDF_BYTES:
        raise InboxError('PDF는 5MB 이하의 올바른 문서여야 합니다.')
    try:
        # 원문은 표준 입력으로만 보내고 macOS 파서의 진단은 로그에 남기지 않는다.
        result=subprocess.run([sys.executable,'-I',__file__,'--probe'],input=raw,
                              stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                              env={'PATH':'/usr/bin:/bin'},timeout=20)
        if result.returncode or not result.stdout.strip().isdigit():raise ValueError()
        pages=int(result.stdout)
        if not 1<=pages<=MAX_PDF_PAGES:raise ValueError()
        return pages
    except (OSError,ValueError,subprocess.TimeoutExpired):
        raise InboxError('PDF를 읽지 못했습니다. 암호 없는 10쪽 이하 PDF를 확인하세요.') from None

def render_pdf(raw, page):
    from inbox_files import InboxError
    from pathlib import Path
    if not isinstance(page,int) or isinstance(page,bool) or not 1<=page<=MAX_PDF_PAGES:
        raise InboxError('PDF 쪽수를 확인하세요.')
    try:
        program=str(Path(__file__).with_name('inbox_pdf_render.py'))
        result=subprocess.run([sys.executable,'-I',program,str(page)],input=raw,stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL,env={'PATH':'/usr/bin:/bin'},timeout=20)
        if result.returncode or not result.stdout.startswith(b'\xff\xd8') or len(result.stdout)>3*1024*1024:raise ValueError()
        return result.stdout
    except (OSError,ValueError,subprocess.TimeoutExpired):
        raise InboxError('PDF 미리보기를 만들지 못했습니다.') from None

if __name__ == '__main__' and sys.argv[1:] == ['--probe']:
    try:
        body=sys.stdin.buffer.read(MAX_PDF_BYTES+1)
        if not body.startswith(b'%PDF-') or len(body)>MAX_PDF_BYTES:raise ValueError()
        print(_page_count(body))
    except Exception:
        sys.exit(1)
