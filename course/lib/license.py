"""Ilson serial verification and offline lease state, stdlib only.

Pure-Python Ed25519 is not constant-time and has not received a security audit.
Only use signing on Jake's trusted Studio, never in a network service.
"""
import argparse
import base64
import getpass
import os
if os.name == 'nt':
    import msvcrt
else:
    import fcntl
import hashlib
import json
from pathlib import Path
import re
import secrets
import stat
import struct
import sys
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

# Public verification key only; the signing seed stays on the issuing Studio.
PUBLIC_KEYS = {1: bytes.fromhex('6455f743370eba4adf230aeb65b23fc2cd4e0ff7df35108e48e2c63bf0f35feb')}
API_URL = 'https://ilson-license.vercel.app'
DOMAIN = b'ILSON-LICENSE-V1\0'
GRACE = 14 * 86400
CHECK_INTERVAL = 86400
Q = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, Q - 2, Q) % Q
I = pow(2, (Q - 1) // 4, Q)
IDENTITY = (0, 1, 1, 0)


def recover_x(y, sign):
    if y >= Q:
        raise ValueError('invalid point')
    x2 = (y*y - 1) * pow(D*y*y + 1, Q - 2, Q) % Q
    x = pow(x2, (Q + 3) // 8, Q)
    if (x*x - x2) % Q:
        x = x * I % Q
    if (x*x - x2) % Q or (x == 0 and sign):
        raise ValueError('invalid point')
    return Q - x if (x & 1) != sign else x


def decode_point(data):
    if len(data) != 32:
        raise ValueError('invalid point')
    value = int.from_bytes(data, 'little')
    y, sign = value & ((1 << 255)-1), value >> 255
    x = recover_x(y, sign)
    return (x, y, 1, x*y % Q)


def add(p, q):
    x1,y1,z1,t1 = p
    x2,y2,z2,t2 = q
    a = (y1-x1)*(y2-x2) % Q
    b = (y1+x1)*(y2+x2) % Q
    c = 2*D*t1*t2 % Q
    d = 2*z1*z2 % Q
    e,f,g,h = b-a,d-c,d+c,b+a
    return (e*f % Q, g*h % Q, f*g % Q, e*h % Q)


def mul(p, n):
    r = IDENTITY
    while n:
        if n & 1:
            r = add(r,p)
        p = add(p,p)
        n >>= 1
    return r


def encode_point(p):
    x,y,z,_ = p
    zinv = pow(z,Q-2,Q)
    x,y = x*zinv % Q,y*zinv % Q
    return (y | ((x & 1) << 255)).to_bytes(32,'little')


B = decode_point(bytes.fromhex('5866666666666666666666666666666666666666666666666666666666666666'))


def public_key(seed):
    if len(seed) != 32:
        raise ValueError('invalid seed')
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], 'little')
    a = (a & ((1 << 254)-8)) | (1 << 254)
    return encode_point(mul(B,a))


def sign(seed, message):
    h = hashlib.sha512(seed).digest()
    a = (int.from_bytes(h[:32], 'little') & ((1 << 254)-8)) | (1 << 254)
    pub = public_key(seed)
    r = int.from_bytes(hashlib.sha512(h[32:] + message).digest(), 'little') % L
    encoded_r = encode_point(mul(B,r))
    k = int.from_bytes(hashlib.sha512(encoded_r + pub + message).digest(),'little') % L
    return encoded_r + ((r + k*a) % L).to_bytes(32,'little')


def verify(pub, message, signature):
    try:
        if len(pub) != 32 or len(signature) != 64:
            return False
        a, r = decode_point(pub), decode_point(signature[:32])
        s = int.from_bytes(signature[32:],'little')
        if s >= L or encode_point(a) == encode_point(IDENTITY):
            return False
        if encode_point(mul(a,L)) != encode_point(IDENTITY) or encode_point(mul(r,L)) != encode_point(IDENTITY):
            return False
        k = int.from_bytes(hashlib.sha512(signature[:32]+pub+message).digest(),'little') % L
        return secrets.compare_digest(encode_point(mul(B,s)), encode_point(add(r,mul(a,k))))
    except (ValueError, TypeError):
        return False


def encode_serial(payload, seed):
    if len(payload) != 29:
        raise ValueError('invalid payload')
    data = payload + sign(seed, DOMAIN + payload)
    raw = base64.b32encode(data).decode('ascii').rstrip('=')
    return 'ILSON-' + '-'.join(raw[i:i+5] for i in range(0,len(raw),5))


def parse_serial(value, now=None):
    if len(value) > 512:
        raise ValueError('INVALID_SERIAL')
    clean = re.sub(r'[\s-]', '', value).upper()
    if not clean.startswith('ILSON') or not re.fullmatch(r'ILSON[A-Z2-7]{149}', clean):
        raise ValueError('INVALID_SERIAL')
    text = clean[5:]
    try:
        raw = base64.b32decode(text + '='*((-len(text)) % 8))
        if len(raw) != 93 or base64.b32encode(raw).decode().rstrip('=') != text:
            raise ValueError()
        payload, signature = raw[:29], raw[29:]
        version,kid,ident,cohort,plan,issued,expires = struct.unpack('>BB16sHBII',payload)
        pub = PUBLIC_KEYS.get(kid)
        if version != 1 or not cohort or plan not in (1,2) or not pub or not verify(pub,DOMAIN+payload,signature):
            raise ValueError()
        if expires == 0xffffffff and plan != 1 or expires != 0xffffffff and expires <= issued:
            raise ValueError()
        now = int(time.time() if now is None else now)
        if issued > now + 300:
            raise ValueError('CLOCK_ERROR')
        if expires != 0xffffffff and now >= expires:
            raise ValueError('EXPIRED')
        return {'id':ident.hex(),'cohort':cohort,'plan':plan,'issued':issued,'expires':expires,'kid':kid,'payload_hash':hashlib.sha256(payload).hexdigest()}
    except (ValueError, KeyError, struct.error) as exc:
        if str(exc) in ('CLOCK_ERROR','EXPIRED'):
            raise
        raise ValueError('INVALID_SERIAL') from None


ELEVATED_OWNER_HINT = ('관리자 권한 PowerShell에서 만든 파일이라 지금 창에서 열 수 없습니다. '
                       '「관리자: Windows PowerShell」을 열고 ilson doctor --fix-permissions 를 한 번 실행한 뒤 다시 시도해주세요.')


class ElevatedOwnerError(ValueError):
    """An elevated ("관리자") session left an object this window cannot read or repair."""
    def __init__(self):
        super().__init__('ELEVATED_OWNER')


# Shared by the private check and the tree repair. The verdicts are pure functions, so tests
# can run them under pwsh on any host. Trusted owners: this user or BUILTIN\Administrators (the
# default owner of everything an elevated token creates). Trusted grants (Allow only): this user,
# SYSTEM, Administrators, CREATOR OWNER, OWNER RIGHTS (Python 3.13+ mkdir(0o700) uses the last
# three). A file owned by another real user, one granting anybody else or one with a Deny entry
# is never repaired, by either script.
#
# Elevated tokens hold privileges a same-user process could borrow by swapping a path that was
# already checked (junction, hard link). An elevated token therefore never changes an object by
# path: it opens a handle that does not follow reparse points, checks that the handle is still
# the object at the checked path (final path, one link, no reparse point, same verdict) and sets
# owner/DACL on that handle. A normal token keeps the plain path route: it has no privilege a
# redirect could borrow, and it does not pay for compiling the handle helper.
# C# for the elevated handle route. It travels in ILSON_ACL_CS, not in the encoded command,
# which must stay under the 32,767-character command-line limit.
ACL_HANDLE_CS = r'''
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Text;
using Microsoft.Win32.SafeHandles;
public static class IlsonAclHandle {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern SafeFileHandle CreateFileW(string name, uint access, uint share, IntPtr sa, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool GetFileInformationByHandle(SafeFileHandle h, [Out] uint[] info);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern uint GetFinalPathNameByHandleW(SafeFileHandle h, StringBuilder path, uint size, uint flags);
    [DllImport("advapi32.dll")]
    static extern uint GetSecurityInfo(SafeFileHandle h, int type, uint info, out IntPtr owner, out IntPtr group, out IntPtr dacl, out IntPtr sacl, out IntPtr sd);
    [DllImport("advapi32.dll")]
    static extern uint SetSecurityInfo(SafeFileHandle h, int type, uint info, byte[] owner, byte[] group, byte[] dacl, byte[] sacl);
    [DllImport("advapi32.dll")]
    static extern uint GetSecurityDescriptorLength(IntPtr sd);
    [DllImport("kernel32.dll")]
    static extern IntPtr LocalFree(IntPtr p);
    static void Fail(int code) {
        if (code == 5) { throw new UnauthorizedAccessException(); }
        throw new IOException("ILSON_WIN32_" + code);
    }
    public static SafeFileHandle Open(string path) {
        // READ_CONTROL|WRITE_DAC|WRITE_OWNER|FILE_READ_ATTRIBUTES, share all, OPEN_EXISTING,
        // FILE_FLAG_BACKUP_SEMANTICS (directories)|FILE_FLAG_OPEN_REPARSE_POINT (never follow).
        SafeFileHandle h = CreateFileW(path, 0xE0080, 7, IntPtr.Zero, 3, 0x02200000, IntPtr.Zero);
        if (h.IsInvalid) { int code = Marshal.GetLastWin32Error(); h.Dispose(); Fail(code); }
        return h;
    }
    public static uint[] Info(SafeFileHandle h) {
        uint[] info = new uint[13];
        if (!GetFileInformationByHandle(h, info)) { Fail(Marshal.GetLastWin32Error()); }
        return new uint[] { info[0], info[10] };
    }
    public static string FinalPath(SafeFileHandle h) {
        StringBuilder text = new StringBuilder(32768);
        uint n = GetFinalPathNameByHandleW(h, text, 32768, 0);
        if (n == 0 || n >= 32768) { Fail(Marshal.GetLastWin32Error()); }
        return text.ToString();
    }
    public static byte[] Read(SafeFileHandle h) {
        IntPtr o, g, d, s, sd;
        uint code = GetSecurityInfo(h, 1, 5, out o, out g, out d, out s, out sd);
        if (code != 0) { Fail((int)code); }
        try {
            byte[] bytes = new byte[GetSecurityDescriptorLength(sd)];
            Marshal.Copy(sd, bytes, 0, bytes.Length);
            return bytes;
        } finally { LocalFree(sd); }
    }
    public static void Apply(SafeFileHandle h, byte[] descriptor, bool dacl) {
        RawSecurityDescriptor raw = new RawSecurityDescriptor(descriptor, 0);
        byte[] owner = new byte[raw.Owner.BinaryLength];
        raw.Owner.GetBinaryForm(owner, 0);
        byte[] list = null;
        uint info = 1;
        if (dacl) {
            list = new byte[raw.DiscretionaryAcl.BinaryLength];
            raw.DiscretionaryAcl.GetBinaryForm(list, 0);
            info = 0x80000005;
        }
        uint code = SetSecurityInfo(h, 1, info, owner, null, list, null);
        if (code != 0) { Fail((int)code); }
    }
}
'''

ACL_VERDICT_PS = r'''
function Test-IlsonTrustedGrants($Rules, [string]$Me) {
    $trusted = @($Me, 'S-1-5-18', 'S-1-5-32-544', 'S-1-3-0', 'S-1-3-4')
    foreach ($rule in @($Rules)) { if (-not $rule.Allow -or $trusted -notcontains $rule.Sid) { return $false } }
    return $true
}
function Get-IlsonPrivateVerdict([string]$Owner, $Rules, [string]$Me) {
    $rules = @($Rules)
    if (-not $Owner) { return 'denied' }
    $userOnly = $rules.Count -gt 0
    foreach ($rule in $rules) { if ($rule.Sid -ne $Me -or -not $rule.Allow) { $userOnly = $false } }
    if ($Owner -eq $Me -and $userOnly) { return 'ok' }
    if ($Owner -ne $Me -and $Owner -ne 'S-1-5-32-544') { return 'foreign' }
    if (-not (Test-IlsonTrustedGrants $rules $Me)) { return 'foreign' }
    return 'repair'
}
function Get-IlsonTreeVerdict([string]$Owner, $Rules, [string]$Me, [bool]$Protected) {
    $rules = @($Rules)
    if (-not $Owner) { return 'denied' }
    # OWNER RIGHTS grants the owner: Python 3.13+ mkdir(0o700) in a normal window gives
    # owner = this user and a protected SY/BA/OW DACL. That is the user's own folder.
    $hasMe = @($rules | Where-Object { $_.Allow -and ($_.Sid -eq $Me -or ($Owner -eq $Me -and $_.Sid -eq 'S-1-3-4')) }).Count -gt 0
    if ($Owner -eq $Me -and $hasMe) { return 'ok' }
    if ($Owner -ne $Me -and $Owner -ne 'S-1-5-32-544') { return 'foreign' }
    if (-not (Test-IlsonTrustedGrants $rules $Me)) { return 'foreign' }
    if ($Protected) { return 'fix-private' }
    return 'fix-owner'
}
function Get-IlsonAclFacts($Acl) {
    $owner = $Acl.GetOwner([Security.Principal.SecurityIdentifier])
    $rules = @(foreach ($rule in $Acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        New-Object PSObject -Property @{ Sid = $rule.IdentityReference.Value; Allow = ($rule.AccessControlType -eq 'Allow') }
    })
    $value = $null
    if ($owner) { $value = $owner.Value }
    return @{ Owner = $value; Rules = $rules; Protected = $Acl.AreAccessRulesProtected }
}
function New-IlsonPrivateAcl($Item, $Me) {
    if ($Item.PSIsContainer) {
        $acl = New-Object Security.AccessControl.DirectorySecurity
        $flags = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit
    } else {
        $acl = New-Object Security.AccessControl.FileSecurity
        $flags = [Security.AccessControl.InheritanceFlags]::None
    }
    $acl.SetOwner($Me)
    $acl.SetAccessRuleProtection($true, $false)
    $rule = New-Object Security.AccessControl.FileSystemAccessRule($Me, 'FullControl', $flags, 'None', 'Allow')
    $acl.AddAccessRule($rule)
    return $acl
}
function Test-IlsonGuarded {
    $principal = New-Object Security.Principal.WindowsPrincipal ([Security.Principal.WindowsIdentity]::GetCurrent())
    return ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or
            $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::BackupOperator))
}
function ConvertTo-IlsonLongPath([string]$Path) {
    if ($Path.StartsWith('\\?\')) { return $Path }
    if ($Path.StartsWith('\\')) { return '\\?\UNC\' + $Path.Substring(2) }
    return '\\?\' + $Path
}
function Test-IlsonSamePath([string]$Final, [string]$Path) {
    if ($Final.StartsWith('\\?\UNC\')) { $Final = '\\' + $Final.Substring(8) }
    elseif ($Final.StartsWith('\\?\')) { $Final = $Final.Substring(4) }
    return $Final.TrimEnd('\') -ieq $Path.TrimEnd('\')
}
function Open-IlsonHandle([string]$Path) {
    if (-not ('IlsonAclHandle' -as [type])) { $null = Add-Type -TypeDefinition $env:ILSON_ACL_CS }
    return [IlsonAclHandle]::Open((ConvertTo-IlsonLongPath $Path))
}
function Close-IlsonHandle($Handle) { $Handle.Dispose() }
function Get-IlsonHandleState($Handle, [bool]$Container) {
    $info = [IlsonAclHandle]::Info($Handle)
    if ($Container) { $acl = New-Object Security.AccessControl.DirectorySecurity } else { $acl = New-Object Security.AccessControl.FileSecurity }
    $acl.SetSecurityDescriptorBinaryForm([IlsonAclHandle]::Read($Handle))
    return @{ Reparse = (($info[0] -band 0x400) -ne 0); Links = [int]$info[1]; Final = [IlsonAclHandle]::FinalPath($Handle); Facts = (Get-IlsonAclFacts $acl) }
}
function Set-IlsonHandleSecurity($Handle, $Me, $Acl) {
    if ($Acl) { [IlsonAclHandle]::Apply($Handle, $Acl.GetSecurityDescriptorBinaryForm(), $true); return }
    $owner = New-Object Security.AccessControl.FileSecurity
    $owner.SetOwner($Me)
    [IlsonAclHandle]::Apply($Handle, $owner.GetSecurityDescriptorBinaryForm(), $false)
}
function Test-IlsonVerdict($Facts, [string]$Me, [string]$Kind, [string]$Want) {
    if (-not $Want) { return $true }
    if ($Kind -eq 'private') { $verdict = Get-IlsonPrivateVerdict $Facts.Owner $Facts.Rules $Me }
    else { $verdict = Get-IlsonTreeVerdict $Facts.Owner $Facts.Rules $Me $Facts.Protected }
    return $verdict -eq $Want
}
# Want '' = a new object (create), 'repair'/'fix-private' = owner + user-only DACL, 'fix-owner' = owner only.
# Returns $false, changing nothing, when the guarded checks refuse the object.
function Invoke-IlsonChange([string]$Path, $Item, $Me, [string]$Kind, [string]$Want, [bool]$Guarded) {
    $acl = $null
    if ($Want -ne 'fix-owner') { $acl = New-IlsonPrivateAcl $Item $Me }
    if (-not $Guarded) {
        if ($acl) { $null = Set-Acl -LiteralPath $Path -AclObject $acl }
        else {
            # Owner only. The inherited DACL stays exactly as it is.
            $owner = $Item.GetAccessControl([Security.AccessControl.AccessControlSections]::Owner)
            $owner.SetOwner($Me)
            $null = $Item.SetAccessControl($owner)
        }
        return $true
    }
    $handle = Open-IlsonHandle $Path
    try {
        $state = Get-IlsonHandleState $handle ([bool]$Item.PSIsContainer)
        if ($state.Reparse -or $state.Links -gt 1 -or -not (Test-IlsonSamePath $state.Final $Path)) { return $false }
        if (-not (Test-IlsonVerdict $state.Facts $Me.Value $Kind $Want)) { return $false }
        $null = Set-IlsonHandleSecurity $handle $Me $acl
    } finally { $null = Close-IlsonHandle $handle }
    return $true
}
function Test-IlsonDenied($Record) {
    $e = $Record.Exception
    while ($e) {
        if ($e -is [UnauthorizedAccessException] -or $e -is [Security.AccessControl.PrivilegeNotHeldException]) { return $true }
        $e = $e.InnerException
    }
    return $false
}
'''

# Exit 0 ok (checked, created or repaired), 1 fail closed, 3 elevated leftover this window cannot fix.
ACL_PRIVATE_PS = ACL_VERDICT_PS + r'''
$ErrorActionPreference = 'Stop'
try {
    $p = $env:ILSON_ACL_TARGET
    $me = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $item = Get-Item -LiteralPath $p -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { exit 1 }
    $want = ''
    if ($env:ILSON_ACL_CREATE -ne '1') {
        $facts = Get-IlsonAclFacts (Get-Acl -LiteralPath $p)
        $want = Get-IlsonPrivateVerdict $facts.Owner $facts.Rules $me.Value
        if ($want -eq 'ok') { exit 0 }
        if ($want -eq 'denied') { exit 3 }
        if ($want -ne 'repair') { exit 1 }
    }
    # Same as the license lock: owner = this user even in an elevated token, user-only DACL.
    if (-not (Invoke-IlsonChange $p $item $me 'private' $want (Test-IlsonGuarded))) { exit 1 }
    $facts = Get-IlsonAclFacts (Get-Acl -LiteralPath $p)
    if ((Get-IlsonPrivateVerdict $facts.Owner $facts.Rules $me.Value) -ne 'ok') { exit 1 }
    exit 0
} catch {
    if (Test-IlsonDenied $_) { exit 3 }
    exit 1
}
'''

# Walks the given roots (never through reparse points). Prints one line of counts:
# checked repaired admin_owned no_access foreign error skipped
# foreign also counts objects the guarded (elevated) route refused: a second hard link, a path
# that no longer leads to the checked object, or a verdict that changed in between.
ACL_TREE_PS = ACL_VERDICT_PS + r'''
$ErrorActionPreference = 'Stop'
$me = [Security.Principal.WindowsIdentity]::GetCurrent().User
$repair = $env:ILSON_ACL_REPAIR -eq '1'
$guarded = $repair -and (Test-IlsonGuarded)
$limit = [int]$env:ILSON_ACL_LIMIT
$n = @{ checked = 0; repaired = 0; admin = 0; denied = 0; foreign = 0; error = 0; skipped = 0 }
$stack = New-Object System.Collections.Stack
foreach ($root in @($env:ILSON_ACL_ROOTS -split "`n" | Where-Object { $_ })) {
    if (Test-Path -LiteralPath $root) { $stack.Push($root) }
}
while ($stack.Count -gt 0) {
    $p = $stack.Pop()
    if ($n.checked -ge $limit) { $n.skipped++; continue }
    try {
        $item = Get-Item -LiteralPath $p -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { $n.skipped++; continue }
        $n.checked++
        $facts = Get-IlsonAclFacts (Get-Acl -LiteralPath $p)
        $verdict = Get-IlsonTreeVerdict $facts.Owner $facts.Rules $me.Value $facts.Protected
        if ($verdict -eq 'denied') { $n.denied++; continue }
        if ($verdict -eq 'foreign') { $n.foreign++; continue }
        if ($verdict -ne 'ok') {
            if (-not $repair) { $n.admin++ }
            elseif (Invoke-IlsonChange $p $item $me 'tree' $verdict $guarded) { $n.repaired++ }
            else { $n.foreign++; continue }
        }
        if ($item.PSIsContainer) {
            foreach ($child in @(Get-ChildItem -LiteralPath $p -Force)) { $stack.Push($child.FullName) }
        }
    } catch {
        if ($_.Exception -is [Management.Automation.ItemNotFoundException]) { $n.skipped++ }
        elseif (Test-IlsonDenied $_) { $n.denied++ } else { $n.error++ }
    }
}
'ILSON_ACL ' + $n.checked + ' ' + $n.repaired + ' ' + $n.admin + ' ' + $n.denied + ' ' + $n.foreign + ' ' + $n.error + ' ' + $n.skipped
'''


def _powershell(script, env, capture=False):
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                          env=dict(os.environ, ILSON_ACL_CS=ACL_HANDLE_CS, **env), stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE if capture else subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=120)


def windows_acl(path, create=False):
    """Create/check a user-only Windows DACL with this user as owner. Fail closed.

    An object left by an elevated session (owner BUILTIN\\Administrators, no foreign grant)
    is repaired in the same call; another user's object is never accepted.
    """
    try:
        # Absolute, so the elevated route can compare it with the handle's final path.
        result = _powershell(ACL_PRIVATE_PS, {'ILSON_ACL_TARGET': os.path.abspath(str(path)), 'ILSON_ACL_CREATE': '1' if create else '0'})
    except (OSError, subprocess.SubprocessError):
        raise ValueError('STORAGE_ERROR') from None
    if result.returncode == 3:
        raise ElevatedOwnerError()
    if result.returncode:
        raise ValueError('STORAGE_ERROR')


def windows_tree(roots, repair=False, limit=5000):
    """Count (and optionally repair) objects under roots that an elevated session left behind."""
    try:
        result = _powershell(ACL_TREE_PS, {'ILSON_ACL_ROOTS': '\n'.join(os.path.abspath(str(p)) for p in roots),
                                           'ILSON_ACL_REPAIR': '1' if repair else '0', 'ILSON_ACL_LIMIT': str(int(limit))},
                             capture=True)
    except (OSError, subprocess.SubprocessError):
        raise ValueError('STORAGE_ERROR') from None
    lines = result.stdout.decode('ascii', errors='replace').split()
    if result.returncode or len(lines) < 8 or lines[-8] != 'ILSON_ACL' or not all(v.isdigit() for v in lines[-7:]):
        raise ValueError('STORAGE_ERROR')
    return dict(zip(('checked', 'repaired', 'admin_owned', 'no_access', 'foreign', 'error', 'skipped'), map(int, lines[-7:])))


def private_dir(home):
    path = Path(home) / 'state' / 'license'
    parts = (Path(home), path.parent, path) if os.name == 'nt' else (path.parent, path)
    for part in parts:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (os.name == 'nt' and getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError('STORAGE_ERROR')
    existed = path.exists()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError('STORAGE_ERROR')
    if os.name == 'nt':
        windows_acl(path, create=not existed)
    elif info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('STORAGE_ERROR')
    return path


def safe_read(path):
    if os.name == 'nt':
        path.lstat()  # Preserve FileNotFoundError for a not-yet-activated user.
        windows_acl(path)
    fd = os.open(str(path), os.O_RDONLY | getattr(os,'O_NOFOLLOW',0))
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_size > 8192 or
                (os.name != 'nt' and (st.st_uid != os.getuid() or st.st_mode & 0o077))):
            raise ValueError('STORAGE_ERROR')
        with os.fdopen(fd,'r',encoding='utf-8') as f:
            fd = -1
            return f.read()
    finally:
        if fd >= 0:
            os.close(fd)


def safe_write(path, value):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('STORAGE_ERROR')
    fd, name = tempfile.mkstemp(prefix='.license-',dir=str(path.parent))
    try:
        if os.name == 'nt':
            windows_acl(name, create=True)
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def request(action, serial, device, url=None):
    url = API_URL if url is None else url
    if not url or urllib.parse.urlparse(url).scheme != 'https':
        raise OSError('server unavailable')
    nonce = secrets.token_hex(16)
    body = json.dumps({'serial':serial,'device_id':device,'nonce':nonce}).encode()
    req = urllib.request.Request(url.rstrip('/')+'/api/v1/'+action,body,{'Content-Type':'application/json','Cache-Control':'no-store'},method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=5) as response:
            result = json.loads(response.read(8193))
    except urllib.error.HTTPError as e:
        if e.code not in (400,403,409):
            raise OSError('server unavailable') from None
        try:
            result = json.loads(e.read(8193))
        except (ValueError, OSError):
            raise OSError('invalid response') from None
    except (OSError,ValueError):
        raise OSError('server unavailable') from None
    if not isinstance(result,dict) or result.get('nonce') != nonce or not isinstance(result.get('server_time'),int):
        raise OSError('invalid response')
    if result.get('status') not in ('active','revoked','expired','payment_due','device_limit','device_not_registered','invalid_serial'):
        raise OSError('invalid response')
    return result


def _evaluate(home, serial=None, force=False, now=None, transport=request):
    now = int(time.time() if now is None else now)
    path = private_dir(home)
    state_path = path / 'state.json'
    try:
        state = json.loads(safe_read(state_path))
        if not isinstance(state,dict):
            raise ValueError('STORAGE_ERROR')
    except FileNotFoundError:
        state = {}
    if serial is None:
        try:
            serial = safe_read(path/'serial').strip()
        except FileNotFoundError:
            return False, 'NO_LICENSE'
    info = parse_serial(serial,now)
    same = state.get('id') == info['id']
    if not same:
        state = {'id':info['id'], 'first':now, 'last_success':None, 'registered':False, 'last_observed':now}
    try:
        device = safe_read(path/'device-id').strip()
        if not re.fullmatch('[0-9a-f]{64}',device):
            raise ValueError('STORAGE_ERROR')
    except FileNotFoundError:
        device = secrets.token_hex(32)
        safe_write(path/'device-id',device)
    previous = state.get('last_observed',now)
    clock_error = now < previous - 300
    due = force or clock_error or bool(state.get('denied')) or not state.get('last_success') or now >= state['last_success']+CHECK_INTERVAL
    result = None
    if due:
        try:
            result = transport('check' if state.get('registered') else 'activate',serial,device)
        except OSError:
            pass
    if result is not None and result.get('status') == 'device_not_registered' and state.get('registered'):
        # A released device must be registered again through the same limit check.
        # A transport failure here cannot turn an explicit denial into a lease.
        try:
            result = transport('activate',serial,device)
        except OSError:
            pass
    if result is not None:
        server_time = result['server_time']
        if abs(now-server_time) > 300:
            return False,'CLOCK_ERROR'
        clock_error = False
        status = result['status']
        if status != 'active':
            state.update({'denied':status,'last_observed':now})
            # A rejected replacement serial must not overwrite the prior license state.
            if same:
                safe_write(state_path,json.dumps(state))
            return False,status.upper()
        state.update({'registered':True,'last_success':now,'denied':None,'paid_until':result.get('paid_until')})
    if clock_error:
        return False,'CLOCK_ERROR'
    if state.get('denied'):
        return False,state['denied'].upper()
    deadline = (state.get('last_success') or state['first']) + GRACE
    if info['expires'] != 0xffffffff:
        deadline = min(deadline,info['expires'])
    if now >= deadline:
        return False,'GRACE_EXPIRED'
    state['last_observed'] = now
    safe_write(path/'serial',serial)
    safe_write(state_path,json.dumps(state))
    return True, 'ACTIVE' if state.get('last_success') else 'OFFLINE_GRACE'


def evaluate(home, serial=None, force=False, now=None, transport=request):
    path = private_dir(home)
    lock_path = path / 'lock'
    created = False
    if os.name == 'nt':
        try:
            lock = os.open(str(lock_path), os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
        except FileExistsError:
            windows_acl(lock_path)
            lock = os.open(str(lock_path), os.O_RDWR)
    else:
        lock = os.open(str(lock_path), os.O_RDWR | os.O_CREAT | getattr(os,'O_NOFOLLOW',0), 0o600)
    try:
        info = os.fstat(lock)
        if (not stat.S_ISREG(info.st_mode) or
                (os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077))):
            raise ValueError('STORAGE_ERROR')
        if os.name == 'nt':
            windows_acl(lock_path, create=created)
            os.lseek(lock, 0, os.SEEK_SET)
            msvcrt.locking(lock, msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lock, fcntl.LOCK_EX)
        return _evaluate(home, serial, force, now, transport)
    finally:
        os.close(lock)


def deactivate(home):
    path = private_dir(home)
    serial = safe_read(path/'serial').strip()
    device = safe_read(path/'device-id').strip()
    result = request('deactivate', serial, device)
    if result.get('status') != 'active' or abs(int(time.time())-result['server_time']) > 300:
        raise ValueError('STORAGE_ERROR')
    for name in ('serial','state.json'):
        (path/name).unlink(missing_ok=True)
    return True

def main():
    parser = argparse.ArgumentParser(description='일손 라이선스')
    parser.add_argument('--home',default=os.environ.get('ILSON_HOME',str(Path.home()/'ilson')))
    parser.add_argument('action',choices=('activate','status','check','deactivate'))
    parser.add_argument('serial',nargs='?')
    parser.add_argument('--stdin',action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'deactivate':
            deactivate(args.home)
            print('이 기기의 라이선스를 해제했습니다.')
            return 0
        serial = args.serial
        if args.action == 'activate' and serial is None:
            serial = sys.stdin.read(513) if args.stdin else getpass.getpass('시리얼을 붙여넣으세요: ')
        ok, code = evaluate(args.home,serial,force=args.action in ('activate','status'))
        if args.action != 'check' or not ok:
            print(('라이선스 확인: ' if ok else '라이선스 확인 필요: ') + code + ('' if ok else ' — ilson license activate'))
        if ok and args.action == 'status':
            directory = private_dir(args.home)
            info = parse_serial(safe_read(directory/'serial').strip())
            state = json.loads(safe_read(directory/'state.json'))
            deadline = (state.get('last_success') or state['first']) + GRACE
            if info['expires'] != 0xffffffff:
                deadline = min(deadline, info['expires'])
            print('일련번호 끝:', info['id'][-8:], '플랜:', '일시불' if info['plan'] == 1 else '월 납부')
            print('서명 만료:', '무기한' if info['expires'] == 0xffffffff else time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(info['expires'])))
            print('마지막 서버 확인:', time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(state['last_success'])) if state.get('last_success') else '없음')
            print('오프라인 사용 기한:',time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(deadline)))
            if state.get('paid_until'):
                print('마지막 확인 납부 기한:',time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(state['paid_until'])))
        return 0 if ok else 1
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as e:
        if isinstance(e, ElevatedOwnerError):
            print('라이선스 확인 필요: ELEVATED_OWNER — ' + ELEVATED_OWNER_HINT, file=sys.stderr)
            return 1
        code = str(e) if str(e) in ('INVALID_SERIAL','EXPIRED','CLOCK_ERROR','STORAGE_ERROR') else 'STORAGE_ERROR'
        print('라이선스 확인 필요: ' + code + ' — ilson license activate',file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
