"""Native progress uses only local Python children; no model, network or paid retrieval."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'template/lib'))
from research import native
from research.run import ResearchError
from test_native_research import candidate, events, URL

REAL_POPEN = subprocess.Popen


def tool(name='WebSearch', key='tool-1'):
    return {'type': 'assistant', 'message': {'content': [
        {'type': 'tool_use', 'id': key, 'name': name, 'input': {'url': URL, 'query': 'private-query'}}]}}


class NativeProgressTests(unittest.TestCase):
    @contextmanager
    def cli(self, script, provider='claude'):
        calls, children = [], []
        def spawn(args, **kwargs):
            calls.append((args, kwargs))
            out = args[args.index('-o') + 1] if provider == 'codex' else None
            prelude = ('import json,os,pathlib,signal,subprocess,sys,time\n'
                       'def emit(value): print(json.dumps(value),flush=True)\n'
                       'candidate=' + repr(candidate()) + '\n'
                       'def finish():\n')
            prelude += (' pathlib.Path(' + repr(out) + ').write_text(json.dumps(candidate))\n' if out else
                        ' emit({"type":"result","structured_output":candidate})\n')
            proc = REAL_POPEN([sys.executable, '-u', '-c', prelude + script], **kwargs)
            children.append(proc)
            return proc
        with patch.object(native.shutil, 'which', return_value=sys.executable), patch.object(native.subprocess, 'Popen', side_effect=spawn):
            try:
                yield calls, children
            finally:
                for proc in children:
                    if proc.poll() is None:
                        native.stop_process_group(proc)

    def test_progress_arrives_before_exit_for_both_providers(self):
        for provider, event in [('claude', tool('WebFetch')), ('codex', events()[0])]:
            with self.subTest(provider=provider), self.cli('emit(' + repr(event) + ');time.sleep(.2);finish()', provider) as (calls, children):
                rows, metrics = [], {}
                def progress(**row):
                    self.assertIsNone(children[0].poll(), 'event must arrive while process is alive')
                    rows.append(row)
                result, observed = native.execute(provider, 'selected-model', 'private prompt', {}, progress=progress, metrics=metrics)
                self.assertEqual(result, candidate())
                self.assertIn(event, observed)
                self.assertEqual(rows, [{'stage': 'reading' if provider == 'claude' else 'searching'}])
                self.assertEqual(len(calls), 1)
                self.assertLess(metrics['first_web_tool_seconds'], metrics['subprocess_seconds'])
                self.assertLessEqual(metrics['cli_spawn_seconds'], metrics['first_event_seconds'])
                self.assertEqual(metrics['web_tool_started_count'], int(provider == 'claude'))
                self.assertEqual(metrics['web_tool_completed_count'], int(provider == 'codex'))
                self.assertNotIn('private', json.dumps(metrics))
                self.assertNotIn(URL, json.dumps(metrics))

    def test_large_image_stdin_and_stderr_do_not_deadlock_or_leak(self):
        image = {'media_type': 'image/jpeg', 'data': 'A' * 320000}
        script = ('os.write(2,b"private-stderr"*200000)\n'
                  'data=json.loads(sys.stdin.buffer.read())\n'
                  'assert len(data["message"]["content"][0]["source"]["data"])==320000\n'
                  'emit(' + repr(tool()) + ')\nfinish()')
        with self.cli(script) as (calls, _):
            metrics = {}
            result, _ = native.execute('claude', '', 'private prompt', {}, image, timeout=4, metrics=metrics)
            self.assertEqual(result, candidate())
            self.assertEqual(metrics['stderr_bytes'], len(b'private-stderr') * 200000)
            self.assertNotIn('private', json.dumps(metrics))
            self.assertNotIn('private prompt', calls[0][0])

    def test_ignores_malformed_json_and_nested_events_without_claiming_progress(self):
        malformed = [[], None, {'item': []}, {'type': 'item.completed', 'item': {'type': 'web_search', 'results': [None]}},
                     {'message': []}, {'message': {'content': [None, {'type': 'tool_use', 'name': 'WebFetch'}]}},
                     {'message': {'content': [{'type': 'tool_result', 'tool_use_id': []}]}}]
        script = ('os.write(1,b"not-json\\n\\xff\\n")\n' +
                  '\n'.join('emit(' + repr(e) + ')' for e in malformed) + '\nfinish()')
        with self.cli(script):
            metrics, rows = {}, []
            _, observed = native.execute('claude', '', 'prompt', {}, metrics=metrics, progress=lambda **row: rows.append(row))
            self.assertEqual(metrics['malformed_event_count'], 4)
            self.assertEqual(metrics['web_tool_started_count'], 0)
            self.assertIsNone(metrics['first_web_tool_seconds'])
            self.assertEqual(rows, [])
            self.assertEqual(native.evidence(observed, 'claude'), ({}, 0))
            # Structurally malformed source events must not create evidence or crash validation.
            self.assertEqual(native.evidence(malformed, 'codex'), ({}, 1))

    def test_output_event_count_line_and_total_size_limits_cleanup(self):
        cases = [('MAX_EVENT_BYTES', 128, 'os.write(1,b"x"*256);time.sleep(30)', '이벤트 크기'),
                 ('MAX_STDOUT_BYTES', 128, 'os.write(1,b"{}\\n"*100);time.sleep(30)', '출력 크기'),
                 ('MAX_EVENTS', 2, 'emit({});emit({});emit({});time.sleep(30)', '이벤트 수')]
        for setting, limit, script, error in cases:
            with self.subTest(setting=setting), patch.object(native, setting, limit), self.cli(script) as (_, children):
                with self.assertRaisesRegex(ResearchError, error):
                    native.execute('claude', '', 'prompt', {}, timeout=2)
                self.assertIsNotNone(children[0].poll())
                self.assertTrue(children[0].stdout.closed)
                self.assertTrue(children[0].stderr.closed)

    def test_timeout_kills_stubborn_process_group(self):
        script = 'signal.signal(signal.SIGTERM,signal.SIG_IGN);emit(' + repr(tool()) + ');time.sleep(30)'
        with self.cli(script) as (_, children), patch.object(native.os, 'killpg', wraps=os.killpg) as killpg:
            with self.assertRaisesRegex(ResearchError, '시간이 초과'):
                native.execute('claude', '', 'prompt', {}, timeout=.15)
            self.assertEqual(children[0].returncode, -signal.SIGKILL)
            self.assertEqual([call.args[1] for call in killpg.call_args_list], [signal.SIGTERM, signal.SIGKILL])

    def test_timeout_cleans_descendant_pipe_after_leader_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'descendant'
            child_script = 'import time;time.sleep(30)'
            script = ('child=subprocess.Popen([sys.executable,"-c",' + repr(child_script) + '])\n'
                      'pathlib.Path(' + repr(str(marker)) + ').write_text(str(child.pid))\n')
            with self.cli(script) as (_, children):
                with self.assertRaisesRegex(ResearchError, '시간이 초과'):
                    native.execute('claude', '', 'prompt', {}, timeout=.2)
                self.assertIsNotNone(children[0].poll())
                pid = int(marker.read_text())
                # A reparented child may briefly be a zombie; it must not remain running.
                with REAL_POPEN(['ps', '-o', 'stat=', '-p', str(pid)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as check:
                    state = check.communicate(timeout=2)[0].strip()
                self.assertTrue(not state or state.startswith('Z'), state)

    def test_callback_error_is_sanitized_cleans_child_and_does_not_retry(self):
        def callback(**row):
            if row['stage'] == 'searching':
                raise ValueError('private-callback-error')
        with self.cli('emit(' + repr(tool()) + ');time.sleep(30)') as (calls, children), patch.object(native, 'load', return_value={'provider': 'claude', 'model': 'selected-model'}), patch('research.multi_source.tavily') as retrieval:
            with self.assertRaises(native.ProgressError) as raised:
                native.research('question', 'all', '.', progress=callback)
            self.assertNotIn('private', str(raised.exception))
            self.assertEqual(len(calls), 1)
            self.assertIsNotNone(children[0].poll())
            retrieval.assert_not_called()

    def test_success_no_duplicate_call_numeric_metrics_and_existing_security_flags(self):
        event = events()[0]
        for provider in ('claude', 'codex'):
            web = tool() if provider == 'claude' else event
            extra = ({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'tool-1', 'content': 'Links: ' + json.dumps([{'url': URL}])}]}} if provider == 'claude' else {})
            script = 'emit(' + repr(web) + ');emit(' + repr(extra) + ');finish()'
            with self.subTest(provider=provider), self.cli(script, provider) as (calls, _), patch.object(native, 'load', return_value={'provider': provider, 'model': 'selected-model'}), patch('research.multi_source.tavily') as retrieval:
                result = native.research('private question', 'all', '.')
                self.assertEqual(len(calls), 1)
                retrieval.assert_not_called()
                self.assertEqual(result['metrics']['native_attempt_count'], 1)
                self.assertEqual(result['metrics']['retry_count'], 0)
                self.assertEqual(result['metrics']['supplement_seconds'], 0)
                self.assertEqual(result['metrics']['tool_events'], 1)
                for value in result['metrics']['native_attempts'][0].values():
                    self.assertTrue(value is None or type(value) in (int, float) and math.isfinite(value) and value >= 0)
                args, kwargs = calls[0]
                self.assertTrue(kwargs['start_new_session'])
                self.assertNotEqual(Path(kwargs['cwd']), Path.cwd())
                self.assertFalse(Path(kwargs['cwd']).exists())
                self.assertIn('selected-model', args)
                if provider == 'claude':
                    self.assertEqual(args[args.index('--effort') + 1], 'medium')
                    self.assertEqual(args[args.index('--tools') + 1], 'WebSearch,WebFetch')
                    self.assertEqual(args[args.index('--allowedTools') + 1], 'WebSearch,WebFetch')
                    self.assertEqual(args[args.index('--permission-mode') + 1], 'dontAsk')
                    self.assertEqual(args[args.index('--setting-sources') + 1], '')
                    self.assertIn('--strict-mcp-config', args)
                    self.assertEqual(args[args.index('--mcp-config') + 1], '{"mcpServers":{}}')
                    self.assertIn('--no-session-persistence', args)
                else:
                    self.assertEqual(args[-1], '-')
                    self.assertIn('--ignore-user-config', args)
                    self.assertIn('--ephemeral', args)
                    self.assertIn('read-only', args)
                    self.assertIn('features.shell_tool=false', args)
                    self.assertIn('model_reasoning_effort="medium"', args)

    def test_retry_reports_honest_stage_and_keeps_attempt_timings_and_model(self):
        rows, calls = [], []
        def execute(provider, model, prompt, schema, image, **kwargs):
            calls.append((provider, model, prompt, kwargs['timeout']))
            kwargs['metrics'].update(subprocess_seconds=.01, first_web_tool_seconds=None)
            if len(calls) == 1:
                raise ResearchError('실제 검색에서 확인되지 않은 출처 주소')
            return candidate(), []
        supplement = [dict(candidate()['sources'][0], content='test', read_status='read')]
        with patch.object(native, 'execute', side_effect=execute), patch.object(native, 'load', return_value={'provider': 'codex', 'model': 'selected-model'}), patch.object(native.shutil, 'which', return_value='synthetic'), patch('research.multi_source.tavily', return_value=supplement) as retrieval:
            result = native.research('question', 'all', '.', progress=lambda **row: rows.append(row))
        self.assertEqual([r['stage'] for r in rows], ['running', 'retrying', 'answering'])
        self.assertEqual([(p, m, t) for p, m, _, t in calls], [('codex', 'selected-model', 300), ('codex', 'selected-model', 180)])
        self.assertIn('6회와 8회', calls[0][2])
        self.assertEqual(result['metrics']['native_attempt_count'], 2)
        self.assertEqual(result['metrics']['retry_count'], 1)
        self.assertEqual(len(result['metrics']['native_attempts']), 2)
        self.assertIsNone(result['metrics']['native_attempts'][0]['validation_seconds'])
        self.assertIsNotNone(result['metrics']['native_attempts'][1]['validation_seconds'])
        retrieval.assert_called_once()

    def test_source_validation_rejection_is_timed_and_retries_without_weakening_gate(self):
        invalid = candidate()
        invalid['sources'][0]['url'] = 'https://example.org/unobserved'
        supplement = [dict(candidate()['sources'][0], content='test', read_status='read')]
        with patch.object(native, 'execute', side_effect=[(invalid, events()), (candidate(), events())]) as execute, patch.object(native, 'load', return_value={'provider': 'codex', 'model': 'selected-model'}), patch.object(native.shutil, 'which', return_value='synthetic'), patch('research.multi_source.tavily', return_value=supplement):
            result = native.research('question', 'all', '.')
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(result['metrics']['retry_count'], 1)
        self.assertEqual(result['coverage']['attempts'], ['codex-native', 'tavily-supplement'])
        self.assertIn('실제 검색에서 확인되지 않은 출처 주소', result['coverage']['failures'][0])
        self.assertEqual([row['url'] for row in result['sources']], [URL])
        self.assertTrue(all(row['validation_seconds'] is not None for row in result['metrics']['native_attempts']))

    def test_nonzero_exit_does_not_expose_stderr_and_unterminated_json_line_is_parsed(self):
        with self.cli('os.write(2,b"private-stderr-token");sys.exit(7)') as (_, children):
            with self.assertRaises(ResearchError) as raised:
                native.execute('claude', '', 'prompt', {})
            self.assertNotIn('private', str(raised.exception))
            self.assertEqual(children[0].returncode, 7)
        with self.cli('os.write(1,json.dumps({"type":"result","structured_output":candidate}).encode())'):
            result, _ = native.execute('claude', '', 'prompt', {})
            self.assertEqual(result, candidate())

    def test_observed_stage_writes_are_throttled_and_final_pending_state_is_current(self):
        now = [0.0]
        metrics = {'json_event_count': 0, 'web_tool_started_count': 0, 'web_tool_completed_count': 0,
                   'web_tool_failed_count': 0, 'first_web_tool_seconds': None}
        rows = []
        with patch.object(native.time, 'monotonic', side_effect=lambda: now[0]):
            observer = native.WebProgress('claude', lambda **row: rows.append((now[0], row)), metrics, 0)
            observer.observe({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'private planning'}]}})
            self.assertEqual(rows, [])
            observer.observe(tool())
            now[0] = .1; observer.observe(tool('WebFetch', 'fetch-1'))
            now[0] = .5; observer.flush()
            self.assertEqual(len(rows), 1)
            now[0] = 1.0; observer.flush()
            now[0] = 1.1; observer.observe(tool('WebSearch', 'search-2'))
            now[0] = 1.2; observer.observe(tool('WebFetch', 'fetch-2'))
            now[0] = 2.0; observer.flush()
            self.assertEqual(rows, [(0, {'stage': 'searching'}), (1, {'stage': 'reading'})])
            self.assertEqual(metrics['web_tool_started_count'], 4)

    def test_codex_open_and_failed_claude_tool_are_observed_without_false_evidence(self):
        metrics = {'json_event_count': 0, 'web_tool_started_count': 0, 'web_tool_completed_count': 0,
                   'web_tool_failed_count': 0, 'first_web_tool_seconds': None}
        rows = []
        observer = native.WebProgress('codex', lambda **row: rows.append(row), metrics, time.monotonic())
        event = {'type': 'item.completed', 'item': {'id': 'open-1', 'type': 'web_search', 'action': {'type': 'open_page'}}}
        observer.observe(event); observer.observe(event)
        self.assertEqual(rows, [{'stage': 'reading'}])
        self.assertEqual(metrics['web_tool_completed_count'], 1)
        observer = native.WebProgress('claude', None, metrics, time.monotonic())
        fail = {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'fetch-1', 'is_error': True, 'content': 'private'}]}}
        observer.observe(tool('WebFetch', 'fetch-1')); observer.observe(fail); observer.observe(fail)
        self.assertEqual(metrics['web_tool_failed_count'], 1)
        self.assertEqual(native.evidence([tool('WebFetch', 'fetch-1'), fail], 'claude'), ({}, 0))


if __name__ == '__main__':
    unittest.main()
