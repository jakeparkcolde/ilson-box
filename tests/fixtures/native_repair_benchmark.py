"""Compare pinned baseline vs current with fake providers and arbitrary simulated costs.

Run: python3 tests/fixtures/native_repair_benchmark.py
No actual model, network, settings, workspace job or service calls. Local elapsed
includes small injected sleeps; neither timing column predicts live speed.
"""
import copy
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'template/lib'), str(ROOT / 'tests')]
from research import native
from test_native_repair import bad_candidate, body_events, candidate, supplemental

BASELINE = '6c7f2ebcbb4f84f3120e7c4501f7ac26674f38ee'
SIMULATED_SECONDS = {'investigate': 120, 'tavily': 15, 'reinvestigate': 100, 'repair': 8}
LOCAL_DELAYS = {'investigate': .02, 'tavily': .015, 'reinvestigate': .025, 'repair': .005}


def baseline_module():
    source = subprocess.run(['git', 'show', BASELINE+':template/lib/research/native.py'],
                            cwd=ROOT, check=True, capture_output=True, text=True).stdout
    module = types.ModuleType('research._benchmark_baseline')
    module.__package__ = 'research'
    exec(compile(source, '<pinned-native-baseline>', 'exec'), module.__dict__)
    return module


def sample(module, provider):
    clock, phases, web_calls = [0.0], [], [0]
    def phase(name, web=0):
        phases.append(name); web_calls[0] += web
        clock[0] += SIMULATED_SECONDS[name]
        time.sleep(LOCAL_DELAYS[name])
    def execute(selected, model, prompt, schema, *args, **kwargs):
        assert (selected, model) == (provider, 'synthetic-selected-model')
        if not kwargs.get('allow_web', True):
            phase('repair')
            return copy.deepcopy(candidate()), []
        web = body_events(provider)
        phase('investigate' if not phases else 'reinvestigate', module.evidence(web, provider)[1])
        return copy.deepcopy(bad_candidate() if len(phases) == 1 else candidate()), web
    def tavily(*args, **kwargs):
        phase('tavily', 1)
        return supplemental()
    started = time.perf_counter()
    with patch.object(module, 'load', return_value={'provider': provider, 'model': 'synthetic-selected-model'}), \
         patch.object(module, 'execute', side_effect=execute), \
         patch.object(module.shutil, 'which', return_value='synthetic-tool'), \
         patch.object(module.time, 'monotonic', side_effect=lambda: clock[0]), \
         patch('research.multi_source.tavily', side_effect=tavily):
        result = module.research('synthetic public fixture', 'all', '.')
    elapsed = time.perf_counter() - started
    assert result['sources'][0]['url'] == candidate()['sources'][0]['url']
    assert result['claims'] == candidate()['claims']
    assert result['verification']['policy'] == native.POLICY
    return {'provider_phases': phases, 'counted_web_calls': web_calls[0],
            'simulated_seconds': clock[0], 'local_elapsed_seconds': round(elapsed, 6),
            'attempts': result['coverage']['attempts'], 'failure_count': len(result['coverage']['failures'])}


def main():
    baseline = baseline_module()
    output = {'kind': 'synthetic_only_not_live_speed', 'baseline': BASELINE,
              'simulated_phase_costs_seconds': SIMULATED_SECONDS,
              'injected_local_delays_seconds': LOCAL_DELAYS, 'providers': {}}
    for provider in ('claude', 'codex'):
        rows = {}
        for name, module in [('baseline', baseline), ('improved', native)]:
            samples = [sample(module, provider) for _ in range(5)]
            rows[name] = dict(samples[0], local_elapsed_median_seconds=round(statistics.median(
                row['local_elapsed_seconds'] for row in samples), 6), local_elapsed_samples_seconds=[
                row['local_elapsed_seconds'] for row in samples])
        assert rows['baseline']['provider_phases'] == ['investigate', 'tavily', 'reinvestigate']
        assert rows['improved']['provider_phases'] == ['investigate', 'repair']
        assert rows['baseline']['counted_web_calls'] == 3
        assert rows['improved']['counted_web_calls'] == 1
        assert rows['baseline']['simulated_seconds'] == 235
        assert rows['improved']['simulated_seconds'] == 128
        output['providers'][provider] = rows
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == '__main__': main()
