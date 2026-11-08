"""별도 프로세스에서 PDF 한 쪽을 메모리 JPEG로 그린다."""
import ctypes as c
import math
import sys

ptr=c.c_void_p
class Point(c.Structure): _fields_=[('x',c.c_double),('y',c.c_double)]
class Size(c.Structure): _fields_=[('width',c.c_double),('height',c.c_double)]
class Rect(c.Structure): _fields_=[('origin',Point),('size',Size)]
class Transform(c.Structure): _fields_=[('a',c.c_double),('b',c.c_double),('c',c.c_double),('d',c.c_double),('tx',c.c_double),('ty',c.c_double)]

def function(lib,name,args,ret):
    f=getattr(lib,name);f.argtypes=args;f.restype=ret;return f

def render(raw,number):
    cf=c.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    cg=c.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    io=c.CDLL('/System/Library/Frameworks/ImageIO.framework/ImageIO')
    data=function(cf,'CFDataCreate',[ptr,ptr,c.c_long],ptr)(None,raw,len(raw))
    provider=function(cg,'CGDataProviderCreateWithCFData',[ptr],ptr)(data)
    doc=function(cg,'CGPDFDocumentCreateWithProvider',[ptr],ptr)(provider)
    if not doc or function(cg,'CGPDFDocumentIsEncrypted',[ptr],c.c_bool)(doc):raise ValueError()
    count=function(cg,'CGPDFDocumentGetNumberOfPages',[ptr],c.c_size_t)(doc)
    if not 1<=number<=count<=10:raise ValueError()
    page=function(cg,'CGPDFDocumentGetPage',[ptr,c.c_size_t],ptr)(doc,number)
    box=function(cg,'CGPDFPageGetBoxRect',[ptr,c.c_int],Rect)(page,0)
    width,height=box.size.width,box.size.height
    if not all(math.isfinite(x) for x in (width,height,box.origin.x,box.origin.y)) or width<=0 or height<=0:raise ValueError()
    scale=min(1200/width,1200/height);w=max(1,int(width*scale));h=max(1,int(height*scale))
    rect=Rect(Point(0,0),Size(w,h))
    space=function(cg,'CGColorSpaceCreateDeviceRGB',[],ptr)()
    ctx=function(cg,'CGBitmapContextCreate',[ptr,c.c_size_t,c.c_size_t,c.c_size_t,c.c_size_t,ptr,c.c_uint32],ptr)(None,w,h,8,0,space,1)
    if not ctx:raise ValueError()
    function(cg,'CGContextSetRGBFillColor',[ptr,c.c_double,c.c_double,c.c_double,c.c_double],None)(ctx,1,1,1,1)
    function(cg,'CGContextFillRect',[ptr,Rect],None)(ctx,rect)
    transform=function(cg,'CGPDFPageGetDrawingTransform',[ptr,c.c_int,Rect,c.c_int,c.c_bool],Transform)(page,0,rect,0,True)
    function(cg,'CGContextConcatCTM',[ptr,Transform],None)(ctx,transform)
    function(cg,'CGContextDrawPDFPage',[ptr,ptr],None)(ctx,page)
    image=function(cg,'CGBitmapContextCreateImage',[ptr],ptr)(ctx)
    output=function(cf,'CFDataCreateMutable',[ptr,c.c_long],ptr)(None,0)
    fmt=function(cf,'CFStringCreateWithCString',[ptr,c.c_char_p,c.c_uint32],ptr)(None,b'public.jpeg',0x08000100)
    destination=function(io,'CGImageDestinationCreateWithData',[ptr,ptr,c.c_size_t,ptr],ptr)(output,fmt,1,None)
    if not image or not output or not fmt or not destination:raise ValueError()
    function(io,'CGImageDestinationAddImage',[ptr,ptr,ptr],None)(destination,image,None)
    if not function(io,'CGImageDestinationFinalize',[ptr],c.c_bool)(destination):raise ValueError()
    length=function(cf,'CFDataGetLength',[ptr],c.c_long)(output)
    if not 1<=length<=3*1024*1024:raise ValueError()
    raw=c.string_at(function(cf,'CFDataGetBytePtr',[ptr],ptr)(output),length)
    function(cf,'CFRelease',[ptr],None)(destination);function(cf,'CFRelease',[ptr],None)(fmt);function(cf,'CFRelease',[ptr],None)(output)
    function(cg,'CGImageRelease',[ptr],None)(image);function(cg,'CGContextRelease',[ptr],None)(ctx);function(cg,'CGColorSpaceRelease',[ptr],None)(space)
    function(cg,'CGPDFDocumentRelease',[ptr],None)(doc);function(cg,'CGDataProviderRelease',[ptr],None)(provider);function(cf,'CFRelease',[ptr],None)(data)
    return raw

if __name__=='__main__':
    try:
        number=int(sys.argv[1]);raw=sys.stdin.buffer.read(5*1024*1024+1)
        if not raw.startswith(b'%PDF-') or len(raw)>5*1024*1024:raise ValueError()
        sys.stdout.buffer.write(render(raw,number))
    except Exception:
        sys.exit(1)
