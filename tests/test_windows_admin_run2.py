"""Windows laptop run 2 (2026-11-20, PS 5.1, elevated SSH): D2, D3, SF1, N1 and notes 2 and N3.

D2: an elevated owner-only fix of a file inheriting OWNER RIGHTS left the user without access
(Windows turned the OWNER RIGHTS entry inherit-only), and the Python verdict counted that
inherit-only entry while the PowerShell one did not. D3: the installer hid why the helper refused.
SF1: the private route anchored to the parent folder only. N1: a folder's new DACL propagated to a
hard-linked file outside the tree.

The SDDL fixtures are the descriptors the laptop printed (realdevice2-win-20261120: s2-run,
sddl-s2, d-run, e-run), with the user's SID written as ME. Where .NET's SDDL hid an inherit-only
entry that icacls showed, both forms are fixtures. Real NTFS behaviour is still a laptop item.
"""
import base64
import fcntl
import gzip
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_windows_elevated_owner import (ME, BA, SY, OW, OI, CI, IO, ID, PWSH, ROOT, PS_STUBS, FakeWin32, node, enc_sd,
                                         guarded_tree, run_acl_script, course_license, payload, diag, server, platform,
                                         launch)
from course_bundle import sources
from pwsh_support import assert_install_result, find_pwsh, offline_env, offline_installer_source, run_pwsh

lic = course_license
WD, BU = 'S-1-1-0', 'S-1-5-32-545'
ALIASES = {'SY': SY, 'BA': BA, 'OW': OW, 'WD': WD, 'BU': BU, 'CO': 'S-1-3-0', 'ME': ME}
ACE_FLAGS = {'OI': OI, 'CI': CI, 'NP': 0x04, 'IO': IO, 'ID': ID}


def sddl(text):
    """The SDDL subset the laptop printed -> (owner, protected, [(sid, allow, flags, mask)])."""
    match = re.fullmatch(r'O:(\w\w)D:((?:P|AI|AR)*)((?:\([^)]*\))*)', text)
    assert match, text
    rules = []
    for kind, flags, rights, sid in re.findall(r'\(([AD]);([A-Z]*);([^;]*);;;([^)]*)\)', match[3]):
        bits = sum(ACE_FLAGS[flags[i:i + 2]] for i in range(0, len(flags), 2))
        rules.append((ALIASES[sid], kind == 'A', bits, 0x1F01FF if rights == 'FA' else int(rights, 16)))
    return ALIASES[match[1]], 'P' in re.findall(r'P|AI|AR', match[2]), rules


# (evidence, SDDL, folder, tree verdict, private verdict)
FIXTURES = [
    ('s2-run rd2-s2real: normal-window Python 0700 folder', 'O:MED:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)', True, 'ok', 'repair'),
    ('s2-run normal.txt', 'O:MED:(A;ID;FA;;;SY)(A;ID;FA;;;BA)(A;ID;FA;;;OW)', False, 'ok', 'repair'),
    ('s2-run elevated.txt before', 'O:BAD:(A;ID;FA;;;SY)(A;ID;FA;;;BA)(A;ID;FA;;;OW)', False, 'fix-private', 'repair'),
    ('s2-run elevated.txt after (icacls OWNER RIGHTS:(IO)(F))', 'O:MED:P(A;;FA;;;SY)(A;;FA;;;BA)(A;IO;FA;;;OW)', False, 'fix-private', 'repair'),
    ('s2-run elevated.txt after, as .NET printed it', 'O:MED:P(A;;FA;;;SY)(A;;FA;;;BA)', False, 'fix-private', 'repair'),
    ('sddl-s2 rd2-s2probe folder (icacls OWNER RIGHTS:(IO)(F))', 'O:MED:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;IO;FA;;;OW)', True, 'fix-private', 'repair'),
    ('sddl-s2 note.txt', 'O:MED:(A;IO;FA;;;OW)(A;ID;FA;;;SY)(A;ID;FA;;;BA)', False, 'fix-private', 'repair'),
    ('sddl-s2 web after the D1 repair', 'O:MED:PAI(A;OICI;FA;;;ME)', True, 'ok', 'ok'),
    ('d-run D1 token: elevated write, inherited user entry', 'O:BAD:(A;ID;FA;;;SY)(A;ID;FA;;;BA)(A;ID;FA;;;ME)', False, 'fix-owner', 'repair'),
    ('d-run D1-b web folder', 'O:BAD:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)', True, 'fix-private', 'repair'),
    ('e-run target-p.txt after propagation', 'O:BAD:AI(A;ID;FA;;;ME)', False, 'fix-owner', 'repair'),
    # Edges of the shared normalisation.
    ('inherit-only user entry on a folder', 'O:BAD:(A;OICIIO;FA;;;ME)(A;;FA;;;SY)', True, 'fix-private', 'repair'),
    ('inherit-only user entry only, own folder', 'O:MED:P(A;OICIIO;FA;;;ME)', True, 'fix-private', 'repair'),
    ('inherit-only foreign grant on a folder still blocks', 'O:BAD:(A;;FA;;;ME)(A;OICIIO;FA;;;WD)', True, 'foreign', 'foreign'),
    ('inherit-only deny on a folder still blocks', 'O:BAD:(A;;FA;;;ME)(D;OICIIO;FA;;;WD)', True, 'foreign', 'foreign'),
    ('inherit-only entry on a file passes nowhere', 'O:BAD:(A;;FA;;;ME)(A;IO;FA;;;WD)', False, 'fix-owner', 'repair'),
    ('inherit-only entry with inherit flags on a file passes nowhere', 'O:BAD:(A;;FA;;;ME)(A;OICIIO;FA;;;WD)', False, 'fix-owner', 'repair'),
    ('inherit-only entry without inherit flags on a folder', 'O:BAD:(A;;FA;;;ME)(A;IO;FA;;;BU)', True, 'fix-owner', 'repair'),
    ('entry with no rights', 'O:BAD:(A;;FA;;;ME)(A;;0x0;;;WD)', False, 'fix-owner', 'repair'),
    ('plain foreign grant', 'O:BAD:(A;ID;FA;;;ME)(A;ID;FA;;;BU)', False, 'foreign', 'foreign'),
]


class VerdictFixtureTests(unittest.TestCase):
    """Real descriptors through each route's own normalisation (binary parse / .NET rule objects)."""

    def python_verdicts(self, text, container):
        owner, protected, rules = sddl(text)
        parsed = lic.parse_security_descriptor(enc_sd(owner, rules, protected), container)
        return lic.tree_verdict(parsed[0], parsed[1], ME, parsed[2]), lic.private_verdict(parsed[0], parsed[1], ME)

    def test_python_route(self):
        for evidence, text, container, tree, private in FIXTURES:
            with self.subTest(evidence):
                self.assertEqual(self.python_verdicts(text, container), (tree, private))

    def test_inherit_only_entries_are_kept_for_trust_but_give_no_access(self):
        owner, protected, rules = sddl('O:MED:P(A;;FA;;;SY)(A;;FA;;;BA)(A;IO;FA;;;OW)')
        # D2 root cause: the old parser counted this OWNER RIGHTS entry and said "ok".
        self.assertEqual(lic.parse_security_descriptor(enc_sd(owner, rules, protected), False)[1], [(SY, True, True), (BA, True, True)])
        self.assertEqual(lic.parse_security_descriptor(enc_sd(owner, rules, protected), True)[1], [(SY, True, True), (BA, True, True)])
        owner, protected, rules = sddl('O:BAD:(A;;FA;;;ME)(A;OICIIO;FA;;;WD)')
        self.assertEqual(lic.parse_security_descriptor(enc_sd(owner, rules, protected), True)[1], [(ME, True, True), (WD, True, False)])

    @unittest.skipUnless(PWSH, 'pwsh required to run the PowerShell ACL logic')
    def test_powershell_route_agrees(self):
        model, lines = [], []
        for index, (_, text, container, _, _) in enumerate(FIXTURES):
            owner, protected, rules = sddl(text)
            path = 'C:\\fixture\\%d' % index
            model.append(node(path, owner, rules, dir=container, protected=protected))
            lines.append("$f = Get-IlsonAclFacts (Get-Acl -LiteralPath '%s') $%s; (Get-IlsonTreeVerdict $f.Owner $f.Rules $env:ACL_ME $f.Protected) + ' ' + "
                         "(Get-IlsonPrivateVerdict $f.Owner $f.Rules $env:ACL_ME)" % (path, 'true' if container else 'false'))
        body = lic.ACL_VERDICT_PS + PS_STUBS + '\n'.join(lines)
        result = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-Command', body], capture_output=True, text=True, timeout=60,
                                stdin=subprocess.DEVNULL, env=dict(os.environ, ACL_MODEL=json.dumps(model), ACL_ME=ME))
        got = result.stdout.splitlines()
        self.assertEqual(len(got), len(FIXTURES), result.stderr)
        for (evidence, _, _, tree, private), line in zip(FIXTURES, got):
            with self.subTest(evidence):
                self.assertEqual(line.split(), [tree, private])


def s2_layout(r='C:\\state'):
    """The laptop's D2 layout: a normal-window Python 0700 folder holding a normal-window file and
    a file an elevated window wrote into it."""
    folder = r + '\\rd2-s2real'
    return r, folder, [
        node(r, ME, [(ME, True, OI | CI)], dir=True, children=[folder]),
        node(folder, ME, [(OW, True, OI | CI), (SY, True, OI | CI), (BA, True, OI | CI)], dir=True, protected=True,
             children=[folder + '\\normal.txt', folder + '\\elevated.txt']),
        node(folder + '\\normal.txt', ME, [(SY, True, ID), (BA, True, ID), (OW, True, ID)]),
        node(folder + '\\elevated.txt', BA, [(SY, True, ID), (BA, True, ID), (OW, True, ID)]),
    ]


def model_verdict(n):
    rules = [(r['sid'], r['allow'], r['flags'], r['mask']) for r in n['rules']]
    owner, parsed, protected = lic.parse_security_descriptor(enc_sd(n['owner'], rules, n['protected']), n['dir'])
    return lic.tree_verdict(owner, parsed, ME, protected)


class OwnerRightsRepairTests(unittest.TestCase):
    """D2 end to end: the elevated handle route (fake Win32) and the normal-window PowerShell route."""

    def test_elevated_file_in_a_python_0700_folder_gets_the_private_repair(self):
        r, folder, model = s2_layout()
        fake = guarded_tree(model, r)
        self.assertEqual(fake.actions, ['hprivate:' + folder + '\\elevated.txt'])
        self.assertEqual(fake.counts, [4, 1, 0, 0, 0, 0, 0, 0])
        by_path = {n['path']: n for n in model}
        self.assertEqual(model_verdict(by_path[folder + '\\elevated.txt']), 'ok')
        self.assertEqual([r['sid'] for r in by_path[folder + '\\elevated.txt']['rules']], [ME])
        # Run again: nothing left, so doctor and --fix-permissions agree (the laptop said 1 and 0).
        again = guarded_tree(model, r)
        self.assertEqual((again.actions, again.counts), ([], [4, 0, 0, 0, 0, 0, 0, 0]))
        if PWSH:
            scan = run_acl_script(lic.ACL_TREE_PS, model, ILSON_ACL_ROOTS=r, ILSON_ACL_REPAIR='0', ILSON_ACL_LIMIT='5000')
            self.assertEqual(scan.counts, [4, 0, 0, 0, 0, 0, 0], scan.stderr)

    def test_leftover_of_the_old_owner_only_fix_is_repaired_by_both_routes(self):
        r = 'C:\\state'
        leftover = r + '\\elevated.txt'
        def layout():
            return [node(r, ME, [(ME, True, OI | CI)], dir=True, children=[leftover]),
                    node(leftover, ME, [(SY, True), (BA, True), (OW, True, IO)], protected=True)]
        fake = guarded_tree(layout(), r)
        self.assertEqual((fake.actions, fake.counts), (['hprivate:' + leftover], [2, 1, 0, 0, 0, 0, 0, 0]))
        if PWSH:
            scan = run_acl_script(lic.ACL_TREE_PS, layout(), ILSON_ACL_ROOTS=r, ILSON_ACL_REPAIR='0', ILSON_ACL_LIMIT='5000')
            self.assertEqual(scan.counts, [2, 0, 1, 0, 0, 0, 0], scan.stderr)  # doctor reports what fix repairs
            fix = run_acl_script(lic.ACL_TREE_PS, layout(), ILSON_ACL_ROOTS=r, ILSON_ACL_REPAIR='1', ILSON_ACL_LIMIT='5000')
            self.assertEqual((fix.actions, fix.counts), (['private:' + leftover], [2, 1, 0, 0, 0, 0, 0]), fix.stderr)

    @unittest.skipUnless(PWSH, 'pwsh required to run the PowerShell ACL logic')
    def test_normal_window_route_gives_the_same_repair(self):
        r, folder, model = s2_layout()
        result = run_acl_script(lic.ACL_TREE_PS, model, ILSON_ACL_ROOTS=r, ILSON_ACL_REPAIR='1', ILSON_ACL_LIMIT='5000')
        self.assertEqual((result.actions, result.counts), (['private:' + folder + '\\elevated.txt'], [4, 1, 0, 0, 0, 0, 0]), result.stderr)

    def test_owner_only_fix_keeps_a_named_user_entry(self):
        # Windows still turns OWNER RIGHTS inherit-only and protects the DACL; the user keeps
        # access through the entry naming them, so the owner-only fix is enough.
        r = 'C:\\ilson-course'
        model = [node(r, ME, [(ME, True, OI | CI)], dir=True, children=[r + '\\token']),
                 node(r + '\\token', BA, [(SY, True, ID), (BA, True, ID), (OW, True, ID), (ME, True, ID)])]
        fake = guarded_tree(model, r)
        self.assertEqual((fake.actions, fake.counts), (['howner:' + r + '\\token'], [2, 1, 0, 0, 0, 0, 0, 0]))
        self.assertTrue(model[1]['protected'])
        self.assertEqual(model_verdict(model[1]), 'ok')

    def test_owner_change_that_still_leaves_no_access_gets_the_private_repair(self):
        # Read-back guard: if an owner-only change ever leaves the user without access, the same
        # handle (or path, in a normal window) gets the full private repair before "repaired".
        r = 'C:\\ilson-course'
        def layout():
            return [node(r, ME, [(ME, True, OI | CI)], dir=True, children=[r + '\\token']),
                    node(r + '\\token', BA, [(SY, True, ID), (BA, True, ID), (ME, True, ID)], ownerdrop=True)]
        model = layout()
        fake = guarded_tree(model, r)
        self.assertEqual((fake.actions, fake.counts), (['howner:' + r + '\\token', 'hprivate:' + r + '\\token'], [2, 1, 0, 0, 0, 0, 0, 0]))
        self.assertEqual(model_verdict(model[1]), 'ok')
        if PWSH:
            result = run_acl_script(lic.ACL_TREE_PS, layout(), ILSON_ACL_ROOTS=r, ILSON_ACL_REPAIR='1', ILSON_ACL_LIMIT='5000')
            self.assertEqual((result.actions, result.counts), (['owner:' + r + '\\token', 'private:' + r + '\\token'], [2, 1, 0, 0, 0, 0, 0]),
                             result.stderr)
        # A change that does not take at all is an error, never counted as repaired.
        model = layout(); model[1]['ignoreset'] = True
        fake = guarded_tree(model, r)
        self.assertEqual(fake.counts, [2, 0, 0, 0, 0, 1, 0, 0])


def guard_layout(r='C:\\ilson-course', linked=True, nested=False):
    """e-run layout: an elevated Python 0700 folder (fix-private) holding a plain file, a hard link
    to a file outside the tree and a junction."""
    p = r + '\\rd2-guard-p'
    leftover = [(SY, True, ID), (BA, True, ID), (OW, True, ID)]
    children = [p + '\\plain.txt', p + '\\jn'] + ([p + '\\sub'] if nested else [p + '\\hl.txt'])
    model = [node(r, ME, [(ME, True, OI | CI)], dir=True, children=[p]),
             node(p, BA, [(OW, True, OI | CI), (SY, True, OI | CI), (BA, True, OI | CI)], dir=True, protected=True, children=children),
             node(p + '\\plain.txt', BA, leftover),
             node(p + '\\jn', ME, [(ME, True)], dir=True, reparse=True, children=['C:\\outside\\inner\\f.txt']),
             node('C:\\outside\\inner\\f.txt', BA, leftover)]
    if nested:
        model += [node(p + '\\sub', BA, leftover, dir=True, children=[p + '\\sub\\deep.txt']),
                  node(p + '\\sub\\deep.txt', BA, leftover, links=2 if linked else 1)]
    else:
        model.append(node(p + '\\hl.txt', BA, leftover, links=2 if linked else 1))
    return r, p, model


class PropagationTests(unittest.TestCase):
    """N1: a folder's DACL is set only when nothing below it has a second hard link."""

    def test_folder_with_a_hard_linked_file_is_refused_and_nothing_propagates(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                r, p, model = guard_layout(nested=nested)
                fake = guarded_tree(model, r)
                self.assertEqual((fake.actions, fake.propagated), ([], []))
                self.assertEqual(fake.counts, [2, 0, 0, 0, 0, 0, 0, 1])  # the folder is refused, its children not walked
                self.assertEqual(model[1]['owner'], BA)

    def test_folder_without_links_is_repaired_and_propagation_skips_the_junction(self):
        r, p, model = guard_layout(linked=False)
        fake = guarded_tree(model, r)
        self.assertEqual(sorted(fake.propagated), sorted([p + '\\plain.txt', p + '\\hl.txt']))
        self.assertIn('hprivate:' + p, fake.actions)
        self.assertNotIn('C:\\outside\\inner\\f.txt', fake.propagated)
        self.assertEqual(fake.counts, [4, 3, 0, 0, 0, 0, 1, 0])  # jn skipped (reparse), plain + hl fixed after propagation

    def test_unreadable_or_oversized_subtree_counts_as_linked(self):
        r, p, model = guard_layout(linked=False)
        next(n for n in model if n['path'] == p + '\\plain.txt')['denied'] = True
        fake = guarded_tree(model, r)
        self.assertEqual((fake.actions, fake.counts), ([], [2, 0, 0, 0, 0, 0, 0, 1]))
        r, p, model = guard_layout(linked=False)
        w32 = FakeWin32(model)
        self.assertTrue(lic._linked_below(w32, p, limit=2))
        self.assertFalse(lic._linked_below(w32, p, limit=3))
        self.assertFalse(w32.handles)

    def test_owner_only_folder_change_never_propagates(self):
        # rd2-guard-o: inherited user entry, so the owner-only fix; no DACL, no propagation. The
        # hard link itself is refused by its own link count.
        r = 'C:\\ilson-course'; o = r + '\\rd2-guard-o'
        model = [node(r, ME, [(ME, True, OI | CI)], dir=True, children=[o]),
                 node(o, BA, [(ME, True, OI | CI | ID), (SY, True, OI | CI | ID)], dir=True, children=[o + '\\hl.txt']),
                 node(o + '\\hl.txt', BA, [(ME, True, ID), (SY, True, ID)], links=2)]
        fake = guarded_tree(model, r)
        self.assertEqual((fake.actions, fake.propagated, fake.counts), (['howner:' + o], [], [3, 1, 0, 0, 0, 0, 0, 1]))

    def test_private_folder_route_refuses_a_hard_linked_child(self):
        folder = 'C:\\state\\curator'
        def layout(links):
            return [node('C:\\state', ME, [(ME, True, OI | CI)], dir=True, children=[folder]),
                    node(folder, BA, [(ME, True, OI | CI | ID)], dir=True, children=[folder + '\\x.json']),
                    node(folder + '\\x.json', ME, [(ME, True)], links=links)]
        fake = FakeWin32(layout(2))
        with self.assertRaises(lic.GuardRefusedError): lic.guarded_private(folder, False, fake, ['C:\\state'])
        self.assertEqual((fake.actions, fake.handles), ([], {}))
        fake = FakeWin32(layout(1))
        lic.guarded_private(folder, False, fake, ['C:\\state'])
        self.assertEqual(fake.actions, ['hprivate:' + folder])


class PrivateAnchorTests(unittest.TestCase):
    """SF1: a private object must sit at its course root's final path plus its literal suffix."""

    def test_private_roots_and_place(self):
        env = {'USERPROFILE': 'C:\\Users\\Me', 'LOCALAPPDATA': 'C:\\Users\\Me\\AppData\\Local', 'ILSON_COURSE_STATE': 'relative',
               'ILSON_COURSE_VAULT': 'D:\\vault'}
        roots = lic.private_roots(env)
        self.assertEqual(roots, ['C:\\Users\\Me\\.ilson-course', 'D:\\vault', 'C:\\Users\\Me', 'C:\\Users\\Me\\AppData\\Local\\ilson-course'])
        place = lic._private_place
        self.assertEqual(place('C:\\Users\\Me\\.ilson-course\\state\\web-admin\\token', roots),
                         ('C:\\Users\\Me\\.ilson-course', ['STATE', 'WEB-ADMIN', 'TOKEN']))
        self.assertEqual(place('c:\\users\\me\\.ILSON-course\\x', roots)[0], 'C:\\Users\\Me\\.ilson-course')  # case-insensitive
        self.assertEqual(place('C:\\Users\\Me\\.ilson-course', roots), ('C:\\Users\\Me', ['.ILSON-COURSE']))  # a root itself
        self.assertEqual(place('C:\\Users\\Me\\.ilson-course-old\\x', roots), ('C:\\Users\\Me', ['.ILSON-COURSE-OLD', 'X']))
        self.assertEqual(place('E:\\elsewhere\\x', roots), ('E:\\elsewhere', ['X']))  # under no root: the parent folder

    def private(self, roots, finals=(), **token):
        target = 'C:\\state\\web-admin\\token'
        model = [node('C:\\state', ME, [(ME, True, OI | CI)], dir=True, children=['C:\\state\\web-admin']),
                 node('C:\\state\\web-admin', ME, [(ME, True, OI | CI)], dir=True, children=[target],
                      **({'hfinal': 'D:\\evil\\web-admin'} if token.pop('swap', False) else {})),
                 node(target, BA, [(ME, True, ID)], **token)]
        fake = FakeWin32(model, finals=finals)
        try:
            lic.guarded_private(target, False, fake, roots)
            outcome = 'ok'
        except lic.GuardRefusedError:
            outcome = 'refused'
        self.assertFalse(fake.handles)
        return outcome, fake.actions

    def test_folder_swapped_below_the_root_is_refused(self):
        swapped = dict(swap=True, hfinal='D:\\evil\\web-admin\\token')
        self.assertEqual(self.private(['C:\\state'], **swapped), ('refused', []))
        # The parent-folder anchor (paths under no known root) cannot see this swap: the SF1 gap.
        self.assertEqual(self.private([], **swapped)[0], 'ok')
        self.assertEqual(self.private(['C:\\state']), ('ok', ['hprivate:C:\\state\\web-admin\\token']))

    def test_indirection_above_the_root_still_works(self):
        # subst drive / 8.3 / case: the root's own final path differs, the suffix below it does not.
        for finals in ([('C:\\', 'E:\\work\\')], [('C:\\state', 'C:\\STATE-LONG~NAME')], [('C:\\state', 'c:\\STATE')]):
            with self.subTest(finals=finals):
                self.assertEqual(self.private(['C:\\state'], finals=finals), ('ok', ['hprivate:C:\\state\\web-admin\\token']))

    def test_object_elsewhere_or_root_link_is_refused(self):
        self.assertEqual(self.private(['C:\\state'], hfinal='C:\\state\\web-admin\\other'), ('refused', []))
        target = 'C:\\state\\token'
        fake = FakeWin32([node('C:\\state', ME, [(ME, True)], dir=True, reparse=True, children=[target]), node(target, BA, [(ME, True)])])
        with self.assertRaises(lic.GuardRefusedError): lic.guarded_private(target, True, fake, ['C:\\state'])
        self.assertEqual(fake.actions, [])

    def test_windows_acl_passes_the_course_roots(self):
        fake = FakeWin32([])
        with patch.object(lic, 'elevated_win32', return_value=fake), patch.object(lic, 'guarded_private') as guarded, \
                patch.object(lic, 'private_roots', return_value=['C:\\state']):
            lic.windows_acl('C:\\state\\token')
        self.assertEqual(guarded.call_args.args[3], ['C:\\state'])


def hold(path):
    """Lock a file the way a running admin server / installer does (flock on this host)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(path, 'a+b')
    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    return stream


class HelperRefusalTests(unittest.TestCase):
    """D3: the helper's fixed refusals reach the student and the diagnostics as a code."""

    def run_helper(self, lib, env):
        bundle = base64.b64encode(gzip.compress(json.dumps(sources()).encode()))
        return subprocess.run([sys.executable, str(ROOT / 'course/install_payload.py'), str(lib)], input=bundle, capture_output=True,
                              timeout=60, env=env)

    def test_each_refusal_prints_only_its_code_and_exits_with_its_number(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp).resolve(); lib = home / 'ilson-course/lib'; lib.mkdir(parents=True)
            env = dict(os.environ, ILSON_COURSE_STATE=str(home / 'state'), HOME=str(home))
            with hold(home / 'state/state/web-admin/server.lock'):
                admin = self.run_helper(lib, env)
            with hold(lib / '.install.lock'):
                busy = self.run_helper(lib, env)
            (lib / 'license.py').write_text('# edited by hand\n')
            modified = self.run_helper(lib, env)
            self.assertFalse((lib / 'ilson.py').exists())
        for result, code in ((admin, 'ADMIN_RUNNING'), (busy, 'INSTALL_BUSY'), (modified, 'HELPER_MODIFIED')):
            with self.subTest(code=code):
                self.assertEqual((result.returncode, result.stdout.decode().split()), (payload.REFUSAL_EXIT[code], ['HELPER_REFUSED=' + code]))
                self.assertEqual(result.stderr, b'')  # no traceback, no path
        self.assertEqual({v: diag.HELPER_REFUSALS[v][0] for v in payload.REFUSAL_EXIT.values()},
                         {v: k for k, v in payload.REFUSAL_EXIT.items()})
        self.assertNotIn(3, diag.HELPER_REFUSALS)  # 3 stays HELPER_PERMISSION_DENIED

    def test_installers_carry_the_same_fixed_text(self):
        ps = (ROOT / 'course/install-windows.ps1').read_text(encoding='ascii')
        body = re.search(r'function Get-IlsonHelperRefusal\(\$Code\) \{\n    switch \(\[int\]\$Code\) \{ (.*?) \}\n', ps).group(1)
        table = {int(code): base64.b64decode(text).decode() for code, text in re.findall(r"(\d+) \{ return \(K '([A-Za-z0-9+/=]+)'\) \}", body)}
        self.assertEqual(table, {code: text for code, (_, text) in diag.HELPER_REFUSALS.items()})
        intel = (ROOT / 'course/install-intel-mac.sh').read_text(encoding='utf-8')
        for code, (_, text) in diag.HELPER_REFUSALS.items():
            self.assertIn("%d) printf '%%s\\n' '학습 도우미: %s' ;;" % (code, text), intel)
            self.assertNotRegex(text, r'[A-Za-z]:\\|/Users/|%')

    def test_doctor_names_the_refusal_of_the_last_course_run(self):
        def events(edition, code, source='native'):
            base = dict(run_id='a' * 32, edition=edition, required=True, attempt=1)
            return [dict(base, seq=1, event='run-start', step_id='bootstrap.start', result='running', reason_code='STARTED'),
                    dict(base, seq=2, event='step-start', step_id='helper.install', result='running', reason_code='STARTED'),
                    dict(base, seq=3, event='step-end', step_id='helper.install', result='failed', reason_code='EXECUTE_FAILED',
                         exit_code=code, exit_source=source),
                    dict(base, seq=4, event='run-end', step_id='finish', result='failed', reason_code='EXECUTE_FAILED')]
        self.assertEqual(diag.summarize_run(events('windows-course', 4))['helper_refusal'], 'ADMIN_RUNNING')
        self.assertEqual(diag.summarize_run(events('intel-course', 6))['helper_refusal'], 'HELPER_MODIFIED')
        for edition, code, source in (('windows-course', 1, 'native'), ('full-mac', 4, 'native'), ('windows-course', 4, 'exception')):
            self.assertNotIn('helper_refusal', diag.summarize_run(events(edition, code, source)))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / 'diag'; run = root / 'runs' / ('a' * 32)
            run.mkdir(parents=True, mode=0o700); root.chmod(0o700); (root / 'runs').chmod(0o700)
            with patch.dict(os.environ, ILSON_DIAGNOSTICS_DIR=str(root)), patch.object(diag, 'read_run', return_value=(events('windows-course', 4), False)), \
                    patch.object(diag, 'course_workspace_app', return_value={'name': 'Herdr', 'state': 'present', 'version': '0.1.15'}), \
                    patch('builtins.print') as output:
                diag.main([], edition='windows-course')
        printed = [c.args[0] for c in output.call_args_list if c.args]
        self.assertIn('설치 중단 이유: ' + diag.HELPER_REFUSALS[4][1], printed)

    def test_windows_installer_shows_why_the_helper_refused(self):
        pwsh = find_pwsh()
        if not pwsh: self.skipTest('pwsh required for mocked PowerShell tests')
        mocks = r'''
function Get-CimInstance { param($ClassName) if ($ClassName -eq 'Win32_OperatingSystem') { [pscustomobject]@{ BuildNumber='26300'; ProductType=1; Caption='test Windows' } } else { [pscustomobject]@{ SystemType='x64-based PC' } } }
function Get-PSDrive { param($Name) [pscustomobject]@{Free=10GB} }
function Find-Claude { [pscustomobject]@{ Source='/usr/bin/true' } }
function Find-Herdr { '/fake/herdr-app.exe' }
function Get-HerdrCourseVersion { '0.1.15' }
function Get-Command {
    [CmdletBinding()] param([string]$Name)
    if ($Name -eq 'python.exe') { return [pscustomobject]@{Source=$env:ILSON_TEST_PYTHON} }
    return $null
}
function New-TestClient {
    $client = [pscustomobject]@{}
    $client | Add-Member ScriptMethod DownloadData { param($url) return ,([Text.Encoding]::UTF8.GetBytes('fixture')) }
    $client | Add-Member ScriptMethod Dispose { }
    return $client
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve(); kit = home / 'kit'; kit.mkdir()
            obs = home / 'Programs/obsidian/Obsidian.exe'; obs.parent.mkdir(parents=True); obs.write_text('fixture')
            runner = home / 'runner.ps1'
            runner.write_text(offline_installer_source()[:-5] + '\n' + mocks + '\nMain\n', encoding='ascii')
            env = offline_env(home, ILSON_COURSE_DRY_RUN='0', ILSON_TEST_PYTHON=sys.executable, ILSON_COURSE_STATE=home / 'state')
            with hold(home / 'state/state/web-admin/server.lock'):
                result = run_pwsh(pwsh, runner, '-KitPath', kit, env=env, timeout=60)
            assert_install_result(self, result, home, {('helper.install', 'EXECUTE_FAILED')}, helper_verified=False)
            self.assertIn('Learn: ' + diag.HELPER_REFUSALS[4][1], result.stdout)
            self.assertNotIn('Learn: DETAIL_SUPPRESSED', result.stdout)
            self.assertIn('HELPER_REFUSED=ADMIN_RUNNING', result.stdout)
            self.assertFalse((home / 'ilson-course/lib/ilson.py').exists())
            run = next((home / 'diagnostics/runs').iterdir())
            events, damaged = diag.read_run(run)
            self.assertFalse(damaged)
            self.assertEqual(diag.summarize_run(events)['helper_refusal'], 'ADMIN_RUNNING')


class RedirectHintTests(unittest.TestCase):
    """Review note 2: `ilson open` names the redirect fix, in the launcher and from the server child."""
    HINT = 'REDIRECTED-HINT-FIXTURE'

    def test_launcher_and_server_child_name_the_redirect_hint(self):
        module = SimpleNamespace(ELEVATED_OWNER_HINT='ELEVATED-ONLY', REDIRECTED_HINT=self.HINT, windows_acl=lambda path, create: (_ for _ in ()).throw(ValueError('PATH_REDIRECTED')))
        with patch.dict(sys.modules, license=module):
            with self.assertRaises(platform.AccessProblem) as caught: platform._windows_acl('C:\\x', False, 'm')
            self.assertEqual((caught.exception.elevated, caught.exception.redirected), (False, True))
            self.assertIn(self.HINT, launch.permission_message(False, True))
            self.assertIn(self.HINT, launch.child_failure(launch.EXIT_REDIRECTED))
            code, message = server.course_failure(server.PermissionProblem('x', redirected=True))
            self.assertEqual(code, launch.EXIT_REDIRECTED); self.assertIn(self.HINT, message)
            code, _ = server.course_failure(platform.AccessProblem('x', redirected=True))
            self.assertEqual(code, launch.EXIT_REDIRECTED)
            args = SimpleNamespace(command='start', home=Path('/nonexistent/home'), vault=Path('/nonexistent'), port=None, force=False)
            module.evaluate = lambda home: (True, 'ACTIVE')
            for error in (platform.AccessProblem('x', redirected=True), ValueError('PATH_REDIRECTED')):
                with self.subTest(error=error), patch.object(launch, 'start', side_effect=error), patch('builtins.print') as output:
                    self.assertEqual(launch.main(args), 1)
                    self.assertIn(self.HINT, output.call_args.args[0])
                    self.assertNotIn('ELEVATED-ONLY', output.call_args.args[0])
        self.assertEqual(len({launch.EXIT_PERMISSION, launch.EXIT_PORT, launch.EXIT_SETTINGS, launch.EXIT_ELEVATED, launch.EXIT_REDIRECTED, 1}), 6)


class SuggestedRulesOwnerTests(unittest.TestCase):
    def test_suggested_rules_are_written_before_the_helper_repair(self):
        # N3: an elevated install wrote CLAUDE-course-suggested.md after the helper's final owner
        # repair, so it stayed owned by Administrators. Now the repair pass covers it.
        source = (ROOT / 'course/install-windows.ps1').read_text(encoding='ascii')
        main = source[source.index('function Main {'):]
        self.assertLess(main.index("'CLAUDE-course-suggested.md'"), main.index("Start-IlsonStep 'helper.install'"))
        self.assertEqual(source.count("'CLAUDE-course-suggested.md'"), 1)


if __name__ == '__main__':
    unittest.main()
