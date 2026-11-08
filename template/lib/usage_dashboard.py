"""Local, limited display of the latest opt-in Claude status-line sample."""
import time
from usage_observer import FRESH_SECONDS, read_json, state_dir, preview


def dashboard(home, now=None):
    now = time.time() if now is None else now
    sample = read_json(state_dir(home) / 'latest.json', None)
    settings = read_json(state_dir(home) / 'alerts.json', {})
    if not isinstance(sample, dict):
        sample = None
    stamp = sample.get('observed_at') if sample else None
    stale = type(stamp) not in (int, float) or stamp > now or now - stamp > FRESH_SECONDS
    if sample:
        # Never expose data outside the observation allowlist, even if a file was edited.
        clean = {'observed_at': stamp, 'cost_usd': sample.get('cost_usd')}
        for key in ('five_hour', 'seven_day'):
            value = sample.get(key)
            clean[key] = {k: value.get(k) for k in ('used_percentage', 'resets_at')} if isinstance(value, dict) else {}
            reset = clean[key].get('resets_at')
            clean[key]['stale'] = stale or (type(reset) in (int, float) and reset <= now)
        sample = clean
    try:
        observer = preview(home)
    except (ValueError, OSError):
        observer = {'enabled': False, 'existing': False, 'supported': False, 'conflict': True}
    return {'sample': sample, 'stale': stale, 'observer': observer,
            'alerts': {'enabled': isinstance(settings, dict) and settings.get('enabled') is True,
                       'threshold': settings.get('threshold', 80) if isinstance(settings, dict) else 80}}
