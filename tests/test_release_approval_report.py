"""Cross-feature check: weekly report reads the real approval ledger."""
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'template/lib'))
import approval_store
import weekly_summary

class ApprovalReportIntegration(unittest.TestCase):
    def test_real_pending_count_without_body_or_title(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'ILSON_HOME': temp}):
            home = Path(temp)
            vault = home / 'vault'
            vault.mkdir()
            approval_store.register_action('release_test', lambda req: None, lambda req: None)
            approval_store.request_approval('release_test', {'channel':'local', 'account':'synthetic', 'object_id':'1'},
                                            'SYNTHETIC_PRIVATE_TITLE', 'SYNTHETIC_PRIVATE_BODY', ttl_hours=72, home=home)
            today = datetime.now(weekly_summary.KST).date()
            report = weekly_summary.build(vault, today)
            self.assertIn('승인 대기: 1건', report)
            self.assertNotIn('SYNTHETIC_PRIVATE_TITLE', report)
            self.assertNotIn('SYNTHETIC_PRIVATE_BODY', report)

if __name__ == '__main__':
    unittest.main()
