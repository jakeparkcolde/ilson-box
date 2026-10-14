"""Claude의 구조화 출력 스트림에서 완성된 주장만 출처 검사 후 전달한다."""
import json
import os
import selectors
import signal
import subprocess
import tempfile
import time

try:
    from .run import ResearchError, parse_answer
except ImportError:
    from run import ResearchError, parse_answer


class PartialAnswer:
    """끊긴 문자열·중괄호를 추측해서 닫지 않는다. JSON decoder가 끝낸 값만 사용한다."""
    def __init__(self, sources, emit):
        self.sources, self.emit = sources, emit
        self.buffer = ''
        self.latest = None
        self.decoder = json.JSONDecoder()

    def reset(self):
        self.buffer = ''
        self.latest = None
        self.emit(None)

    def feed(self, delta):
        if not isinstance(delta, str):
            raise ResearchError('생성 중 답변 형식 오류')
        self.buffer += delta
        if len(self.buffer) > 262144:
            raise ResearchError('생성 중 답변 크기 초과')
        text = self.buffer
        pos = len(text) - len(text.lstrip())
        if pos >= len(text) or text[pos] != '{':
            return
        pos += 1
        claims, comparison = [], None
        try:
            while pos < len(text):
                while pos < len(text) and text[pos] in ' \r\n\t,':
                    pos += 1
                if pos == len(text) or text[pos] == '}':
                    break
                key, pos = self.decoder.raw_decode(text, pos)
                while pos < len(text) and text[pos].isspace():
                    pos += 1
                if pos == len(text):
                    break
                if text[pos] != ':':
                    raise ResearchError('생성 중 답변 JSON 형식 오류')
                pos += 1
                while pos < len(text) and text[pos].isspace():
                    pos += 1
                if key == 'claims' and pos < len(text) and text[pos] == '[':
                    pos += 1
                    while pos < len(text):
                        while pos < len(text) and text[pos] in ' \r\n\t,':
                            pos += 1
                        if pos == len(text):
                            break
                        if text[pos] == ']':
                            pos += 1
                            break
                        value, pos = self.decoder.raw_decode(text, pos)
                        claims.append(value)
                        self._publish(claims, comparison)
                else:
                    value, pos = self.decoder.raw_decode(text, pos)
                    if key == 'comparison':
                        comparison = value
                        self._publish(claims, comparison)
        except json.JSONDecodeError:
            # 불완전한 값은 다음 토큰이 올 때까지 보류한다. 형식·출처 오류는 삼키지 않는다.
            return

    def _publish(self, claims, comparison):
        if not claims:
            return
        if self.latest and (len(claims) < len(self.latest['claims']) or
                            (len(claims) == len(self.latest['claims']) and comparison is None and 'comparison' in self.latest)):
            return
        candidate = parse_answer(json.dumps(dict(claims=claims, comparison=comparison, limitations='')), self.sources)
        if candidate != self.latest:
            self.latest = candidate
            self.emit(candidate)

    def finish(self, envelope):
        if not isinstance(envelope, dict) or envelope.get('is_error') or envelope.get('permission_denials'):
            raise ResearchError('답변 생성이 완료되지 않았습니다')
        candidate = envelope.get('structured_output')
        if not isinstance(candidate, dict):
            try:
                candidate = json.loads(envelope.get('result'))
            except (ValueError, TypeError):
                raise ResearchError('완성된 답변을 확인하지 못했습니다') from None
        checked = parse_answer(json.dumps(candidate), self.sources)
        if self.latest and (checked['claims'][:len(self.latest['claims'])] != self.latest['claims'] or
                            ('comparison' in self.latest and checked.get('comparison') != self.latest['comparison'])):
            raise ResearchError('작성 중 답변과 최종 답변이 다릅니다. 다시 조사하세요')
        return envelope


def generate(args, *, cwd, sources, emit, timeout=150, input_text=None):
    started = time.monotonic()
    # 2026-10-06: CLI 시작·모델 이벤트·실제 문단 표시를 같은 시작점에서 잰다.
    # 미관측은 None으로 남긴다. system/init이나 thinking을 첫 답변으로 세지 않는다.
    metrics = dict(cli_spawn_seconds=None, first_model_event_seconds=None,
                   first_content_delta_seconds=None, first_claim_seconds=None,
                   stream_complete_seconds=None, content_delta_characters=0,
                   structured_output_characters=0)

    def elapsed():
        return round(time.monotonic() - started, 4)

    def publish(candidate):
        # PartialAnswer가 완성된 주장과 출처를 검사한 다음에만 이 함수에 도달한다.
        if candidate is not None and metrics['first_claim_seconds'] is None:
            metrics['first_claim_seconds'] = elapsed()
        emit(candidate)

    parser = PartialAnswer(sources, publish)
    block = None
    envelope = None
    # 외부 stderr에는 인증 정보가 있을 수 있어 응답·로그에 넣지 않는다.
    with tempfile.TemporaryFile() as errors, tempfile.TemporaryFile() as user_input:
        if input_text is not None:
            user_input.write(input_text.encode("utf-8"))
            user_input.seek(0)
        try:
            process = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=errors,
                                       stdin=user_input if input_text is not None else subprocess.DEVNULL, start_new_session=True,
                                       env={**os.environ, 'ILSON_HOME': str(cwd)})
        except OSError:
            raise ResearchError('답변 실행기를 시작하지 못했습니다') from None
        metrics['cli_spawn_seconds'] = elapsed()
        pending = b''
        total = 0
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                eof = False
                while not eof:
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        raise ResearchError('답변 생성 시간이 초과됐습니다')
                    if not selector.select(min(remaining, 1)):
                        continue
                    chunk = os.read(process.stdout.fileno(), 65536)
                    total += len(chunk)
                    if total > 4_000_000:
                        raise ResearchError('답변 스트림 크기 초과')
                    pending += chunk
                    eof = not chunk
                    lines = pending.split(b'\n')
                    pending = lines.pop()
                    if eof and pending:
                        lines.append(pending)
                    for line in lines:
                        if not line.strip():
                            continue
                        try:
                            message = json.loads(line)
                        except (ValueError, UnicodeError):
                            raise ResearchError('답변 스트림 형식 오류') from None
                        if not isinstance(message, dict):
                            raise ResearchError('답변 스트림 형식 오류')
                        if message.get('type') == 'result':
                            envelope = message
                        event = message.get('event', {}) if message.get('type') == 'stream_event' else {}
                        if event and metrics['first_model_event_seconds'] is None:
                            metrics['first_model_event_seconds'] = elapsed()
                        if event.get('type') == 'message_start':
                            block = None
                        content = event.get('content_block', {})
                        if event.get('type') == 'content_block_start' and content.get('type') == 'tool_use' and content.get('name') == 'StructuredOutput':
                            block = event.get('index')
                            parser.reset()
                        delta = event.get('delta', {})
                        generated = None
                        if delta.get('type') == 'text_delta':
                            generated = delta.get('text')
                        elif delta.get('type') == 'input_json_delta':
                            generated = delta.get('partial_json')
                        if isinstance(generated, str) and generated:
                            if metrics['first_content_delta_seconds'] is None:
                                metrics['first_content_delta_seconds'] = elapsed()
                            metrics['content_delta_characters'] += len(generated)
                        if block is not None and event.get('index') == block and delta.get('type') == 'input_json_delta':
                            parser.feed(delta.get('partial_json'))
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise ResearchError('답변 생성 시간이 초과됐습니다')
            try:
                code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                raise ResearchError('답변 생성 시간이 초과됐습니다') from None
            if code:
                raise ResearchError('답변 생성 미완료 — 인증·잔여 한도를 확인하세요')
            checked = parser.finish(envelope)
            structured = checked.get('structured_output')
            if not isinstance(structured, dict):
                # finish가 이미 JSON과 출처를 검증했다. 최종 원문의 문자 수만 남긴다.
                structured = json.loads(checked['result'])
            metrics['structured_output_characters'] = len(json.dumps(structured, ensure_ascii=False, separators=(',', ':')))
            metrics['stream_complete_seconds'] = elapsed()
            return {**checked, '_ilson_stream_metrics': metrics}
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            process.stdout.close()
