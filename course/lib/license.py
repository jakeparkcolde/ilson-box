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


# An elevated window refused a change because the path does not lead plainly to the object (a
# link on the way, a second hard link). Not another user's file: a normal window re-checks it.
REDIRECTED_HINT = ('관리자 권한 창에서는 연결(바로가기)을 거치는 경로의 파일을 안전을 위해 바꾸지 않았습니다. '
                   '일반 PowerShell 창에서 ilson doctor 를 실행해 남은 항목이 있는지 확인해주세요.')

# An elevated window left a folder as it was because its safety scan could not finish (more
# entries than the scan limit, or an entry it could not open). A normal window cannot fix such a
# folder either (it may grant this user nothing), so the hint names the elevated rerun and the
# instructor, never the normal window.
UNSCANNED_HINT = ('관리자 권한 창에서 일부 폴더는 안에 항목이 너무 많거나 열 수 없는 항목이 있어 안전 확인을 끝내지 못했고, 그래서 권한을 바꾸지 않았습니다. '
                  '열린 프로그램을 닫고 「관리자: Windows PowerShell」에서 ilson doctor --fix-permissions 를 다시 실행해주세요. 그래도 남으면 강사에게 확인해주세요.')


# Shared by the private check and the tree repair. The verdicts are pure functions, so tests
# can run them under pwsh on any host. Trusted owners: this user or BUILTIN\Administrators (the
# default owner of everything an elevated token creates). Trusted grants (Allow only): this user,
# SYSTEM, Administrators, CREATOR OWNER, OWNER RIGHTS (Python 3.13+ mkdir(0o700) uses the last
# three). A file owned by another real user, one granting anybody else or one with a Deny entry
# is never repaired, by either script.
#
# Elevated tokens hold privileges a same-user process could borrow by swapping a path that was
# already checked (junction, hard link). An elevated token therefore never changes an object by
# path. Python takes that route itself (ctypes, see "Elevated route" below): no PowerShell process
# and no C# compile. Both scripts refuse to change anything in an elevated token (exit 4), so a
# failed or skipped elevation check in Python can only fail closed.
#
# D2 (laptop run 2, 2026-11-20). Rules carry Effective: false for an inherit-only entry, which
# passes to children but gives the object itself no access; both verdicts count access from
# effective entries only. Get-IlsonAclFacts normalises like parse_security_descriptor, whatever
# .NET already dropped: an entry with no rights, or an inherit-only entry that cannot pass anywhere
# (a file, or no inherit flag), is left out; any other inherit-only entry stays for the trust
# check. An owner change makes Windows turn OWNER RIGHTS entries inherit-only, so an owner-only
# fix ('fix-owner') is chosen only when an entry names this user; otherwise the object gets the
# full private repair. The tree repair reads every change back: an owner-only change that still
# leaves the user without access gets the private repair, anything else not reading back as the
# user's own counts as an error, never as repaired.
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
    $own = $false
    foreach ($rule in $rules) {
        if ($rule.Sid -ne $Me -or -not $rule.Allow) { $userOnly = $false } elseif ($rule.Effective) { $own = $true }
    }
    if ($Owner -eq $Me -and $userOnly -and $own) { return 'ok' }
    if ($Owner -ne $Me -and $Owner -ne 'S-1-5-32-544') { return 'foreign' }
    if (-not (Test-IlsonTrustedGrants $rules $Me)) { return 'foreign' }
    return 'repair'
}
function Get-IlsonTreeVerdict([string]$Owner, $Rules, [string]$Me, [bool]$Protected) {
    $rules = @($Rules)
    if (-not $Owner) { return 'denied' }
    # OWNER RIGHTS grants the owner: Python 3.13+ mkdir(0o700) in a normal window gives
    # owner = this user and a protected SY/BA/OW DACL. That is the user's own folder.
    $hasMe = @($rules | Where-Object { $_.Effective -and $_.Allow -and ($_.Sid -eq $Me -or ($Owner -eq $Me -and $_.Sid -eq 'S-1-3-4')) }).Count -gt 0
    if ($Owner -eq $Me -and $hasMe) { return 'ok' }
    if ($Owner -ne $Me -and $Owner -ne 'S-1-5-32-544') { return 'foreign' }
    if (-not (Test-IlsonTrustedGrants $rules $Me)) { return 'foreign' }
    if ($Protected) { return 'fix-private' }
    $named = @($rules | Where-Object { $_.Effective -and $_.Allow -and $_.Sid -eq $Me }).Count -gt 0
    if ($Owner -eq 'S-1-5-32-544' -and $named) { return 'fix-owner' }
    return 'fix-private'
}
function Get-IlsonAclFacts($Acl, [bool]$Container) {
    $owner = $Acl.GetOwner([Security.Principal.SecurityIdentifier])
    $rules = @(foreach ($rule in $Acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        $inheritOnly = ([int]$rule.PropagationFlags -band 2) -ne 0
        if ([int64]$rule.FileSystemRights -eq 0) { continue }
        if ($inheritOnly -and (-not $Container -or [int]$rule.InheritanceFlags -eq 0)) { continue }
        New-Object PSObject -Property @{ Sid = $rule.IdentityReference.Value; Allow = ($rule.AccessControlType -eq 'Allow'); Effective = -not $inheritOnly }
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
# Want '' = a new object (create), 'repair'/'fix-private' = owner + user-only DACL, 'fix-owner' = owner only.
# Normal (filtered) token only: the scripts exit before this in an elevated one.
function Invoke-IlsonChange([string]$Path, $Item, $Me, [string]$Want) {
    if ($Want -ne 'fix-owner') { $null = Set-Acl -LiteralPath $Path -AclObject (New-IlsonPrivateAcl $Item $Me); return }
    # Owner only. The inherited DACL stays exactly as it is.
    $owner = $Item.GetAccessControl([Security.AccessControl.AccessControlSections]::Owner)
    $owner.SetOwner($Me)
    $null = $Item.SetAccessControl($owner)
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

# Exit 0 ok (checked, created or repaired), 1 fail closed, 3 elevated leftover this window cannot fix,
# 4 elevated token (the change belongs to the Python handle route; nothing was read or changed).
ACL_PRIVATE_PS = ACL_VERDICT_PS + r'''
$ErrorActionPreference = 'Stop'
try {
    if (Test-IlsonGuarded) { exit 4 }
    $p = $env:ILSON_ACL_TARGET
    $me = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $item = Get-Item -LiteralPath $p -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { exit 1 }
    $want = ''
    if ($env:ILSON_ACL_CREATE -ne '1') {
        $facts = Get-IlsonAclFacts (Get-Acl -LiteralPath $p) ([bool]$item.PSIsContainer)
        $want = Get-IlsonPrivateVerdict $facts.Owner $facts.Rules $me.Value
        if ($want -eq 'ok') { exit 0 }
        if ($want -eq 'denied') { exit 3 }
        if ($want -ne 'repair') { exit 1 }
    }
    # Same as the license lock: owner = this user, user-only DACL (normal token; see exit 4 above).
    Invoke-IlsonChange $p $item $me $want
    $facts = Get-IlsonAclFacts (Get-Acl -LiteralPath $p) ([bool]$item.PSIsContainer)
    if ((Get-IlsonPrivateVerdict $facts.Owner $facts.Rules $me.Value) -ne 'ok') { exit 1 }
    exit 0
} catch {
    if (Test-IlsonDenied $_) { exit 3 }
    exit 1
}
'''

# Walks the given roots (never through reparse points). Prints one line of counts:
# checked repaired admin_owned no_access foreign error skipped
# A repair in an elevated token prints ILSON_ACL_GUARDED and exits 4 without reading anything:
# that repair is the Python handle route (guarded_tree).
ACL_TREE_PS = ACL_VERDICT_PS + r'''
$ErrorActionPreference = 'Stop'
function Get-IlsonTreeState([string]$Path, $Item, $Me) {
    $facts = Get-IlsonAclFacts (Get-Acl -LiteralPath $Path) ([bool]$Item.PSIsContainer)
    return (Get-IlsonTreeVerdict $facts.Owner $facts.Rules $Me.Value $facts.Protected)
}
$repair = $env:ILSON_ACL_REPAIR -eq '1'
if ($repair -and (Test-IlsonGuarded)) { 'ILSON_ACL_GUARDED'; exit 4 }
$me = [Security.Principal.WindowsIdentity]::GetCurrent().User
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
        $facts = Get-IlsonAclFacts (Get-Acl -LiteralPath $p) ([bool]$item.PSIsContainer)
        $verdict = Get-IlsonTreeVerdict $facts.Owner $facts.Rules $me.Value $facts.Protected
        if ($verdict -eq 'denied') { $n.denied++; continue }
        if ($verdict -eq 'foreign') { $n.foreign++; continue }
        if ($verdict -ne 'ok') {
            if (-not $repair) { $n.admin++ }
            else {
                Invoke-IlsonChange $p $item $me $verdict
                if ((Get-IlsonTreeState $p $item $me) -ne 'ok') {
                    if ($verdict -ne 'fix-owner') { throw 'ILSON_ACL_UNVERIFIED' }
                    Invoke-IlsonChange $p $item $me 'fix-private'
                    if ((Get-IlsonTreeState $p $item $me) -ne 'ok') { throw 'ILSON_ACL_UNVERIFIED' }
                }
                $n.repaired++
            }
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
                          env=dict(os.environ, **env), stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE if capture else subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=120)


# ---- Elevated route (Windows, Python + ctypes) -------------------------------------------------
# One process, no compile: CreateFileW with FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
# GetFileInformationByHandle, GetFinalPathNameByHandleW, GetSecurityInfo / SetSecurityInfo on that
# handle. The decisions below take the Win32 layer as an argument, so tests drive them with a fake.
#
# Path anchor (F1): legitimate setups reach the course folders indirectly (C:\Users or the profile
# behind a junction, subst or mapped drives, 8.3 names). So an object is accepted when its handle's
# final path lies under the final path of its anchor, resolved through the anchor's own handle:
# the walked root for the tree repair. A single private object (SF1) must sit exactly at its
# course root's final path plus the literal rest of its path (private_roots: state, install,
# vault, profile; the parent folder only for a path under none of them), so a folder swapped for a
# junction anywhere below that root is refused, while indirection above the root still works.
#
# Propagation (N1, laptop 2026-11-20): SetSecurityInfo with a DACL lets the system rewrite the
# inherited entries of existing children by name, outside this guard. That walk does not follow
# junction children, but it does change a hard-linked file whose other name lies outside the tree.
# So a folder's DACL is set only after a scan through handles finds no file with a second link
# below it (_linked_below); otherwise the folder is refused like a link. The scan does not enter a
# protected child (its DACL, and so everything below it, is not rewritten). A scan that cannot
# finish (limit, unreadable entry) refuses the folder under its own count, 'unscanned'. Either
# way the walk still visits the folder's children, each checked and repaired on its own handle
# (review D23 SF-1). Known limit: a same-user process that plants a hard link between that scan
# and the set still wins the race.
FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_REPARSE_POINT = 0x10, 0x400
OPEN_FLAGS = 0x02200000           # FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT
READ_ACCESS = 0x20080             # READ_CONTROL | FILE_READ_ATTRIBUTES
WRITE_ACCESS = 0xE0080            # READ_CONTROL | WRITE_DAC | WRITE_OWNER | FILE_READ_ATTRIBUTES
OWNER_INFO, OWNER_PROTECTED_DACL_INFO = 0x1, 0x80000005  # (PROTECTED_DACL | DACL | OWNER)_SECURITY_INFORMATION
FULL_CONTROL = 0x1F01FF           # FileSystemRights.FullControl, as New-IlsonPrivateAcl grants it
BA = 'S-1-5-32-544'
TRUSTED_GRANTS = ('S-1-5-18', BA, 'S-1-3-0', 'S-1-3-4')


class Win32Error(OSError):
    """A failed Win32 call; code is the Win32 error (5 access denied, 2/3 missing, 32 sharing)."""
    def __init__(self, code):
        super().__init__('ILSON_WIN32_%d' % code)
        self.code = code


def _failure(exc):
    """'denied', 'gone' or 'error' for an exception from the Win32 layer or os."""
    code = getattr(exc, 'code', None) if isinstance(exc, Win32Error) else getattr(exc, 'winerror', None)
    if code is None:
        if isinstance(exc, PermissionError): return 'denied'
        if isinstance(exc, FileNotFoundError): return 'gone'
        return 'error'
    if code == 5: return 'denied'
    if code in (2, 3): return 'gone'
    return 'error'


def sid_text(data, offset=0):
    """Binary SID at offset -> ('S-1-...', length). Strict bounds; ValueError otherwise."""
    if offset < 0 or offset + 8 > len(data) or data[offset] != 1 or data[offset + 1] > 15:
        raise ValueError('SID')
    count = data[offset + 1]
    if offset + 8 + 4 * count > len(data):
        raise ValueError('SID')
    authority = int.from_bytes(data[offset + 2:offset + 8], 'big')
    subs = struct.unpack_from('<%dI' % count, data, offset + 8)
    text = 'S-1-' + (str(authority) if authority < 2**32 else '0x%012X' % authority)
    return text + ''.join('-%d' % value for value in subs), 8 + 4 * count


def sid_bytes(text):
    parts = text.split('-')
    if len(parts) < 3 or parts[0] != 'S' or parts[1] != '1' or len(parts) - 3 > 15:
        raise ValueError('SID')
    authority = int(parts[2], 16) if parts[2].lower().startswith('0x') else int(parts[2])
    subs = [int(value) for value in parts[3:]]
    return bytes((1, len(subs))) + authority.to_bytes(6, 'big') + struct.pack('<%dI' % len(subs), *subs)


def parse_security_descriptor(data, container=True):
    """Self-relative descriptor -> (owner, [(sid, allow, effective)], protected), the facts
    Get-IlsonAclFacts reads. container: the object is a folder (from its handle).

    Entries are normalised as .NET's CommonAcl does and as Get-IlsonAclFacts repeats: no rights
    (mask 0) or an inherit-only entry that cannot pass anywhere (on a file, or without OI/CI) is
    dropped; another inherit-only entry stays for the trust check with effective False, because
    it gives the object itself no access (D2: Windows turns OWNER RIGHTS inherit-only when the
    owner changes). Stricter than .NET where they could differ: a missing DACL means Everyone (as
    .NET reports it), and an ACE that is not a plain allow/deny entry counts as an untrusted grant.
    """
    if len(data) < 20:
        raise ValueError('SD')
    revision, _, control, owner_at, _, _, dacl_at = struct.unpack_from('<BBHIIII', data)
    if revision != 1 or not control & 0x8000:  # SE_SELF_RELATIVE
        raise ValueError('SD')
    owner = sid_text(data, owner_at)[0] if owner_at else None
    protected = bool(control & 0x1000)  # SE_DACL_PROTECTED
    if not control & 0x4 or not dacl_at:  # SE_DACL_PRESENT, NULL DACL
        return owner, [('S-1-1-0', True, True)], protected
    if dacl_at + 8 > len(data):
        raise ValueError('SD')
    _, _, size, count, _ = struct.unpack_from('<BBHHH', data, dacl_at)
    end = dacl_at + size
    if size < 8 or end > len(data):
        raise ValueError('SD')
    rules, at = [], dacl_at + 8
    for _ in range(count):
        if at + 4 > end:
            raise ValueError('SD')
        kind, flags, ace_size = struct.unpack_from('<BBH', data, at)
        if ace_size < 8 or at + ace_size > end:
            raise ValueError('SD')
        if kind in (0, 1):  # ACCESS_ALLOWED_ACE_TYPE, ACCESS_DENIED_ACE_TYPE
            sid = sid_text(data[:at + ace_size], at + 8)[0]
            mask = struct.unpack_from('<I', data, at + 4)[0]
            inherit_only = bool(flags & 0x08)  # INHERIT_ONLY_ACE
            if mask and not (inherit_only and (not container or not flags & 0x03)):  # OBJECT_INHERIT | CONTAINER_INHERIT
                rules.append((sid, kind == 0, not inherit_only))
        else:
            rules.append(('ACE-%d' % kind, False, True))
        at += ace_size
    return owner, rules, protected


def private_dacl(me, container):
    """The DACL New-IlsonPrivateAcl builds: one Allow FullControl entry for this user,
    inherited by subfolders and files (OI|CI) on a folder. Applied as a protected DACL."""
    sid = sid_bytes(me)
    ace = struct.pack('<BBHI', 0, 0x03 if container else 0, 8 + len(sid), FULL_CONTROL) + sid
    return struct.pack('<BBHHH', 2, 0, 8 + len(ace), 1, 0) + ace


# Same tables as Get-IlsonPrivateVerdict / Get-IlsonTreeVerdict (a test runs one table through both).
# A rule is (sid, allow, effective); a pair counts as effective.
def _rules(rules):
    return [(rule[0], rule[1], rule[2] if len(rule) > 2 else True) for rule in rules]


def _trusted(rules, me):
    return all(allow and sid in (me,) + TRUSTED_GRANTS for sid, allow, _ in rules)


def private_verdict(owner, rules, me):
    rules = _rules(rules)
    if not owner: return 'denied'
    if (owner == me and rules and all(sid == me and allow for sid, allow, _ in rules)
            and any(effective for *_, effective in rules)): return 'ok'
    if owner not in (me, BA) or not _trusted(rules, me): return 'foreign'
    return 'repair'


def tree_verdict(owner, rules, me, protected):
    rules = _rules(rules)
    if not owner: return 'denied'
    if owner == me and any(effective and allow and (sid == me or sid == 'S-1-3-4') for sid, allow, effective in rules): return 'ok'
    if owner not in (me, BA) or not _trusted(rules, me): return 'foreign'
    if protected: return 'fix-private'
    # D2: an owner change turns OWNER RIGHTS entries inherit-only, so an owner-only fix is right
    # only when an entry names this user; otherwise the full private repair (see Get-IlsonTreeVerdict).
    named = any(effective and allow and sid == me for sid, allow, effective in rules)
    return 'fix-owner' if owner == BA and named else 'fix-private'


def _final_parts(path):
    """Components of a final path, \\\\?\\ and \\\\?\\UNC\\ removed, compared case-insensitively."""
    if path[:8].upper() == '\\\\?\\UNC\\': path = '\\\\' + path[8:]
    elif path[:4] == '\\\\?\\': path = path[4:]
    unc = path.startswith('\\\\')
    parts = [part for part in path.split('\\') if part]
    # NTFS compares names with a one-to-one upcase table; never let one character become two.
    return [unc] + [''.join(c.upper() if len(c.upper()) == 1 else c for c in part) for part in parts]


def under(final, anchor):
    """True when final is anchor or lies below it, component by component."""
    f, a = _final_parts(final), _final_parts(anchor)
    return len(a) > 1 and f[:len(a)] == a


def long_path(path):
    if path.startswith('\\\\?\\'): return path
    if path.startswith('\\\\'): return '\\\\?\\UNC\\' + path[2:]
    return '\\\\?\\' + path


class GuardRefusedError(ValueError):
    """The elevated route did not change an object it could not tie to its folder (a link, a
    second hard link, a path leading elsewhere, or a verdict that changed in between)."""
    def __init__(self):
        super().__init__('PATH_REDIRECTED')


def _facts(w32, handle, container):
    return parse_security_descriptor(w32.security(handle), container)


def _anchor(w32, path):
    """Final path of a folder through its own handle; None when the folder itself is a link."""
    handle = w32.open(path, False)
    try:
        attributes, _ = w32.info(handle)
        return None if attributes & FILE_ATTRIBUTE_REPARSE_POINT else w32.final_path(handle)
    finally:
        w32.close(handle)


PROPAGATION_SCAN_LIMIT = 5000


def _linked_below(w32, folder, limit=PROPAGATION_SCAN_LIMIT):
    """What a new inheritable DACL on folder could reach, from a scan through handles:
    None when no file with a second hard link lies below it, 'linked' when one does, 'unscanned'
    when the scan could not finish (an entry it cannot open or read, or more than limit entries;
    fail closed). Like the system's propagation, the scan enters neither reparse points nor
    protected children: a protected DACL is not rewritten, so nothing below it changes."""
    import ntpath
    stack, seen = [folder], 0
    try:
        while stack:
            path = stack.pop()
            for name in w32.children(path):
                seen += 1
                if seen > limit:
                    return 'unscanned'
                child = ntpath.join(path, name)
                handle = w32.open(child, False)
                try:
                    attributes, links = w32.info(handle)
                    if attributes & FILE_ATTRIBUTE_REPARSE_POINT:
                        continue
                    container = bool(attributes & FILE_ATTRIBUTE_DIRECTORY)
                    if _facts(w32, handle, container)[2]:
                        continue  # protected: propagation stops here
                finally:
                    w32.close(handle)
                if container:
                    stack.append(child)
                elif links != 1:
                    return 'linked'
    except (OSError, ValueError, struct.error):
        return 'unscanned'
    return None


def _guarded_change(w32, path, anchor, me, kind, want, exact=False, dry=False):
    """Owner (+ user-only protected DACL unless want is 'fix-owner') set on a checked handle, then
    read back on the same handle. Returns 'changed', or, changing nothing:
    'refused' when the handle is not the object at its place (under the anchor, or exactly the
    anchor when exact) or its verdict moved; 'linked' or 'unscanned' when a folder's new DACL could
    propagate to a hard-linked file or the scan could not tell (_linked_below).
    A result that does not read back as the user's own raises STORAGE_ERROR; an owner-only fix that
    left the user without access (OWNER RIGHTS turned inherit-only, D2) gets the full private
    repair first, and raises STORAGE_ERROR when the scan refuses that repair, because the owner
    has already changed. dry: every check on a read handle, then 'changed' without changing."""
    handle = w32.open(path, not dry)
    try:
        attributes, links = w32.info(handle)
        container = bool(attributes & FILE_ATTRIBUTE_DIRECTORY)
        final = w32.final_path(handle)
        placed = _final_parts(final) == _final_parts(anchor) if exact else under(final, anchor)
        if attributes & FILE_ATTRIBUTE_REPARSE_POINT or links != 1 or not placed:
            return 'refused'

        def verdict():
            owner, rules, protected = _facts(w32, handle, container)
            return private_verdict(owner, rules, me) if kind == 'private' else tree_verdict(owner, rules, me, protected)

        if want and verdict() != want:
            return 'refused'
        if want != 'fix-owner' and container:
            scan = _linked_below(w32, path)
            if scan:
                return scan
        if dry:
            return 'changed'
        w32.set_security(handle, sid_bytes(me), None if want == 'fix-owner' else private_dacl(me, container))
        if verdict() == 'ok':
            return 'changed'
        if want != 'fix-owner':
            raise ValueError('STORAGE_ERROR')
        if container and _linked_below(w32, path):
            raise ValueError('STORAGE_ERROR')  # review D23 note 2: the owner is no longer as found
        w32.set_security(handle, sid_bytes(me), private_dacl(me, container))
        if verdict() != 'ok':
            raise ValueError('STORAGE_ERROR')
        return 'changed'
    finally:
        w32.close(handle)


def private_roots(environ=None):
    """Course roots a private object lives under, as the course sets them (literal Windows paths):
    state home, install folder, practice vault, profile (Path.home() is USERPROFILE on Windows).
    The longest one holding the object anchors it."""
    import ntpath
    env = os.environ if environ is None else environ
    home, local = env.get('USERPROFILE'), env.get('LOCALAPPDATA')
    values = [env.get('ILSON_HOME'), env.get('ILSON_COURSE_STATE'), home and ntpath.join(home, '.ilson-course'),
              env.get('ILSON_COURSE_VAULT'), home, local and ntpath.join(local, 'ilson-course')]
    return [ntpath.normpath(value) for value in values if value and ntpath.isabs(value)]


def _private_place(target, roots):
    """(root, suffix components) for target: the longest root strictly above it, compared by
    component without case; the parent folder when none holds it."""
    import ntpath
    parts = _final_parts(target)
    best = None
    for root in roots:
        candidate = _final_parts(root)
        if 1 < len(candidate) < len(parts) and parts[:len(candidate)] == candidate and (best is None or len(candidate) > len(best[1])):
            best = (root, candidate)
    if best is None:
        parent = ntpath.dirname(target)
        best = (parent, _final_parts(parent))
    return best[0], parts[len(best[1]):]


def guarded_private(target, create, w32, roots=()):
    """ACL_PRIVATE_PS for an elevated token, on handles. target is absolute."""
    try:
        me = w32.user_sid()
        if w32.is_reparse(target):
            raise ValueError('STORAGE_ERROR')
        want = ''
        if not create:
            handle = w32.open(target, False)
            try:
                attributes, _ = w32.info(handle)
                owner, rules, _ = _facts(w32, handle, bool(attributes & FILE_ATTRIBUTE_DIRECTORY))
            finally:
                w32.close(handle)
            want = private_verdict(owner, rules, me)
            if want == 'ok': return
            if want == 'denied': raise ElevatedOwnerError()
            if want != 'repair': raise ValueError('STORAGE_ERROR')
        root, suffix = _private_place(target, roots)
        anchor = _anchor(w32, root)
        if anchor is None or not suffix:
            raise GuardRefusedError()
        expected = anchor.rstrip('\\') + '\\' + '\\'.join(suffix)
        result = _guarded_change(w32, target, expected, me, 'private', want, exact=True)
        if result == 'unscanned':
            raise ValueError('STORAGE_ERROR')  # not a link: no redirect hint
        if result != 'changed':
            raise GuardRefusedError()
    except (ElevatedOwnerError, GuardRefusedError):
        raise
    except (OSError, ValueError, struct.error) as exc:
        raise (ElevatedOwnerError() if _failure(exc) == 'denied' else ValueError('STORAGE_ERROR')) from None


TREE_COUNTS = ('checked', 'repaired', 'admin_owned', 'no_access', 'foreign', 'error', 'skipped', 'refused', 'unscanned')


def guarded_tree(roots, limit, w32, repair=True):
    """ACL_TREE_PS for an elevated token, on handles. refused: objects the guard left alone (a link,
    a second hard link, a path leading elsewhere); unscanned: folders left alone because their
    propagation scan could not finish. A folder left alone by its scan still has its children
    walked. repair False: the same checks without changing anything (ilson doctor in an elevated
    window), so an object the repair would refuse is not counted as admin_owned (run 3, N2)."""
    import ntpath
    me = w32.user_sid()
    n = dict.fromkeys(TREE_COUNTS, 0)
    stack = [(root, None) for root in roots if w32.exists(root)]
    while stack:
        path, anchor = stack.pop()
        if n['checked'] >= limit:
            n['skipped'] += 1
            continue
        try:
            if w32.is_reparse(path):
                n['skipped'] += 1
                continue
            n['checked'] += 1
            handle = w32.open(path, False)
            try:
                attributes, _ = w32.info(handle)
                final = w32.final_path(handle)
                if anchor is None:
                    anchor = final  # the root: its own final path, resolved once
                if attributes & FILE_ATTRIBUTE_REPARSE_POINT or not under(final, anchor):
                    n['refused'] += 1
                    continue
                owner, rules, protected = _facts(w32, handle, bool(attributes & FILE_ATTRIBUTE_DIRECTORY))
            finally:
                w32.close(handle)
            verdict = tree_verdict(owner, rules, me, protected)
            if verdict == 'denied':
                n['no_access'] += 1
                continue
            if verdict == 'foreign':
                n['foreign'] += 1
                continue
            if verdict != 'ok':
                result = _guarded_change(w32, path, anchor, me, 'tree', verdict, dry=not repair)
                if result == 'refused':
                    n['refused'] += 1
                    continue  # not tied to its place: never walk below it
                if result == 'linked':
                    n['refused'] += 1
                elif result == 'unscanned':
                    n['unscanned'] += 1
                else:
                    n['repaired' if repair else 'admin_owned'] += 1
            if attributes & FILE_ATTRIBUTE_DIRECTORY:
                stack.extend((ntpath.join(path, name), anchor) for name in w32.children(path))
        except (OSError, ValueError, struct.error) as exc:
            kind = _failure(exc)
            n['skipped' if kind == 'gone' else 'no_access' if kind == 'denied' else 'error'] += 1
    return n


class Win32:
    """The real Win32 layer for the elevated route (Windows only)."""
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.c = ctypes
        k = self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        a = self.advapi = ctypes.WinDLL('advapi32', use_last_error=True)
        H, D, B, P = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, ctypes.c_void_p
        for name, args, result in (
                ('CreateFileW', [wintypes.LPCWSTR, D, D, P, D, D, H], H), ('CloseHandle', [H], B),
                ('GetFileInformationByHandle', [H, P], B), ('GetFinalPathNameByHandleW', [H, wintypes.LPWSTR, D, D], D),
                ('GetCurrentProcess', [], H), ('LocalFree', [P], P)):
            function = getattr(k, name); function.argtypes = args; function.restype = result
        pp = ctypes.POINTER(P)
        for name, args, result in (
                ('GetSecurityInfo', [H, ctypes.c_int, D, pp, pp, pp, pp, pp], D),
                ('SetSecurityInfo', [H, ctypes.c_int, D, P, P, P, P], D), ('GetSecurityDescriptorLength', [P], D),
                ('OpenProcessToken', [H, D, ctypes.POINTER(H)], B), ('GetTokenInformation', [H, ctypes.c_int, P, D, ctypes.POINTER(D)], B),
                ('GetLengthSid', [P], D), ('CheckTokenMembership', [H, P, ctypes.POINTER(B)], B)):
            function = getattr(a, name); function.argtypes = args; function.restype = result
        self._sid = self._guarded = None

    def _error(self, code=None):
        return Win32Error(self.c.get_last_error() if code is None else code)

    def guarded(self):
        """Like Test-IlsonGuarded: Administrators or Backup Operators enabled in this token
        (deny-only in a UAC-filtered token, so a normal window is not guarded)."""
        if self._guarded is None:
            found = False
            for sid in (BA, 'S-1-5-32-551'):
                value = self.c.create_string_buffer(sid_bytes(sid))
                member = self.c.c_long(0)
                if not self.advapi.CheckTokenMembership(None, value, self.c.byref(member)):
                    raise self._error()
                found = found or bool(member.value)
            self._guarded = found
        return self._guarded

    def user_sid(self):
        if self._sid is None:
            c = self.c
            token = c.c_void_p()
            if not self.advapi.OpenProcessToken(self.kernel.GetCurrentProcess(), 0x8, c.byref(token)):  # TOKEN_QUERY
                raise self._error()
            try:
                size = c.c_ulong(0)
                self.advapi.GetTokenInformation(token, 1, None, 0, c.byref(size))  # TokenUser: sizes the buffer
                if not size.value or size.value > 4096:
                    raise self._error()
                buffer = c.create_string_buffer(size.value)
                if not self.advapi.GetTokenInformation(token, 1, buffer, size, c.byref(size)):
                    raise self._error()
                pointer = c.c_void_p.from_buffer(buffer).value  # TOKEN_USER.User.Sid
                self._sid = sid_text(c.string_at(pointer, self.advapi.GetLengthSid(pointer)))[0]
            finally:
                self.kernel.CloseHandle(token)
        return self._sid

    def exists(self, path):
        return os.path.exists(path)

    def is_reparse(self, path):
        return bool(getattr(os.lstat(path), 'st_file_attributes', 0) & FILE_ATTRIBUTE_REPARSE_POINT)

    def children(self, path):
        with os.scandir(path) as entries:
            return [entry.name for entry in entries]

    def open(self, path, write):
        handle = self.kernel.CreateFileW(long_path(path), WRITE_ACCESS if write else READ_ACCESS, 7, None, 3, OPEN_FLAGS, None)
        if handle is None or handle == self.c.c_void_p(-1).value:
            raise self._error()
        return handle

    def close(self, handle):
        self.kernel.CloseHandle(handle)

    def info(self, handle):
        info = (self.c.c_ulong * 13)()  # BY_HANDLE_FILE_INFORMATION
        if not self.kernel.GetFileInformationByHandle(handle, info):
            raise self._error()
        return info[0], info[10]  # dwFileAttributes, nNumberOfLinks

    def final_path(self, handle):
        buffer = self.c.create_unicode_buffer(32768)
        size = self.kernel.GetFinalPathNameByHandleW(handle, buffer, 32768, 0)  # FILE_NAME_NORMALIZED | VOLUME_NAME_DOS
        if not size or size >= 32768:
            raise self._error()
        return buffer.value

    def security(self, handle):
        c = self.c
        owner, group, dacl, sacl, descriptor = (c.c_void_p() for _ in range(5))
        code = self.advapi.GetSecurityInfo(handle, 1, 5, c.byref(owner), c.byref(group), c.byref(dacl), c.byref(sacl), c.byref(descriptor))
        if code:
            raise self._error(code)
        try:
            return c.string_at(descriptor.value, self.advapi.GetSecurityDescriptorLength(descriptor.value))
        finally:
            self.kernel.LocalFree(descriptor.value)

    def set_security(self, handle, owner, dacl):
        c = self.c
        owner_buffer = c.create_string_buffer(owner, len(owner))
        dacl_buffer = None if dacl is None else c.create_string_buffer(dacl, len(dacl))
        code = self.advapi.SetSecurityInfo(handle, 1, OWNER_INFO if dacl is None else OWNER_PROTECTED_DACL_INFO,
                                           owner_buffer, None, dacl_buffer, None)
        if code:
            raise self._error(code)


_WIN32 = []


def elevated_win32():
    """The Win32 layer when this process holds an elevated token, else None (also when ctypes
    or the check fails: the PowerShell route then refuses an elevated token by itself)."""
    if os.name != 'nt':
        return None
    try:
        if not _WIN32:
            _WIN32.append(Win32())
        return _WIN32[0] if _WIN32[0].guarded() else None
    except Exception:
        return None


def windows_acl(path, create=False):
    """Create/check a user-only Windows DACL with this user as owner. Fail closed.

    An object left by an elevated session (owner BUILTIN\\Administrators, no foreign grant)
    is repaired in the same call; another user's object is never accepted.
    """
    target = os.path.abspath(str(path))
    w32 = elevated_win32()
    if w32 is not None:
        return guarded_private(target, create, w32, private_roots())
    try:
        result = _powershell(ACL_PRIVATE_PS, {'ILSON_ACL_TARGET': target, 'ILSON_ACL_CREATE': '1' if create else '0'})
    except (OSError, subprocess.SubprocessError):
        raise ValueError('STORAGE_ERROR') from None
    if result.returncode == 3:
        raise ElevatedOwnerError()
    if result.returncode:
        raise ValueError('STORAGE_ERROR')


def windows_tree(roots, repair=False, limit=5000):
    """Count (and optionally repair) objects under roots that an elevated session left behind.
    refused / unscanned: objects an elevated window leaves alone (guarded_tree). An elevated
    window reads through the same handle checks as its repair, so the counts agree (run 3, N2)."""
    roots = [os.path.abspath(str(p)) for p in roots]
    w32 = elevated_win32()
    if w32 is not None:
        try:
            return guarded_tree(roots, int(limit), w32, repair=repair)
        except (OSError, ValueError):
            raise ValueError('STORAGE_ERROR') from None
    try:
        result = _powershell(ACL_TREE_PS, {'ILSON_ACL_ROOTS': '\n'.join(roots),
                                           'ILSON_ACL_REPAIR': '1' if repair else '0', 'ILSON_ACL_LIMIT': str(int(limit))},
                             capture=True)
    except (OSError, subprocess.SubprocessError):
        raise ValueError('STORAGE_ERROR') from None
    lines = result.stdout.decode('ascii', errors='replace').split()
    if result.returncode or len(lines) < 8 or lines[-8] != 'ILSON_ACL' or not all(v.isdigit() for v in lines[-7:]):
        raise ValueError('STORAGE_ERROR')
    counts = dict(zip(('checked', 'repaired', 'admin_owned', 'no_access', 'foreign', 'error', 'skipped'), map(int, lines[-7:])))
    counts['refused'] = counts['unscanned'] = 0
    return counts


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
        if isinstance(e, GuardRefusedError):
            print('라이선스 확인 필요: PATH_REDIRECTED — ' + REDIRECTED_HINT, file=sys.stderr)
            return 1
        code = str(e) if str(e) in ('INVALID_SERIAL','EXPIRED','CLOCK_ERROR','STORAGE_ERROR') else 'STORAGE_ERROR'
        print('라이선스 확인 필요: ' + code + ' — ilson license activate',file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
