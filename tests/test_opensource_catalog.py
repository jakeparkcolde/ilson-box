"""L0 disclosure/failure boundaries, with no real repositories or services."""
import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'template/lib'))
import opensource_catalog as oc
from opensource_fixtures import NOW, at, repo, catalog, raw


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.now = NOW
        self.document = raw(catalog(repo()))
        self.read = Mock(side_effect=lambda path, limit: (self.document, None))
        self.store = oc.Catalog(self.read, clock=lambda: self.now)

    def snapshot(self, document=None, ident=None):
        if document is not None:
            self.document = raw(document)
        return self.store.snapshot(ident)

    def test_shipped_catalog_is_valid_empty_not_candidates(self):
        document=oc.validate((ROOT/'template'/oc.CATALOG_PATH).read_bytes())
        self.assertEqual(document['repos'], [])
        self.assertGreater(oc.timestamp(document['valid_until']), NOW)
        self.assertEqual(document['signature']['kind'], 'bundled')

    def test_curated_order_and_detail_source_dates_stay_distinct(self):
        first, second = repo(), repo('e'*32, 2)
        first['curated_order']=8
        result=self.snapshot(catalog(first, second))
        self.assertEqual([r['id'] for r in result['repos']], [second['id'], first['id']])
        detail=self.store.snapshot(first['id'])['repo']
        self.assertEqual(detail, first)
        self.assertNotEqual(detail['source']['summary_created_at'], detail['review']['reviewed_at'])
        self.assertFalse(result['runnable'])
        self.assertEqual(self.read.call_args.args, (oc.CATALOG_PATH, oc.MAX_BYTES))

    def test_every_publication_gate_hides_list_detail_and_links(self):
        mutations=[('catalog_approved',False),('runnable',True),('category','unknown'),('one_liner','English only'),
            ('mild_md',''),('difficulty',True),('quick_start_md','FAKE_SECRET'),('preview',dict(approved=False)),
            ('official_url','https://evil.example'),('gitbap_url','javascript:alert(1)')]
        mutations += [('review.'+k,v) for k,v in dict(hidden=True,review_status='pending',metadata_verdict='review',
            content_scan='failed',policy='unknown',rights='unknown',maintenance='unknown',archived=True,
            prohibited=True,requirements_confirmed=False,key_required='unknown',paid_api_required=None,
            target_commit='e'*40,policy_version='unknown',valid_until=at(-1),metadata_checked_at=at(-72*3600)).items()]
        mutations += [('source.'+k,v) for k,v in dict(lang='ja',summary_readme_hash='e'*64,status_checked_at=at(-72*3600),
            summary_created_at=at(1)).items()]
        mutations += [('license.'+k,v) for k,v in dict(spdx='NOASSERTION',reviewed=False,url='https://evil.example').items()]
        for field,value in mutations:
            with self.subTest(field=field):
                row=repo();parts=field.split('.');target=row
                for part in parts[:-1]:target=target[part]
                target[parts[-1]]=value
                store=oc.Catalog(lambda *_:(raw(catalog(row)),None),clock=lambda:NOW)
                listing=store.snapshot();detail=store.snapshot(row['id'])
                self.assertEqual(listing['repos'],[])
                self.assertIsNone(detail['repo'])
                for blocked in (row['full_name'],row['gitbap_url'],row['id'],'FAKE_SECRET'):
                    self.assertNotIn(blocked,json.dumps([listing,detail]))

    def test_missing_required_unknown_fields_and_types_never_default_to_pass(self):
        for key in repo():
            with self.subTest(missing=key):
                row=repo();del row[key]
                store=oc.Catalog(lambda *_:(raw(catalog(row)),None),clock=lambda:NOW)
                self.assertEqual(store.snapshot()['repos'],[])
        for field,value in [('review',None),('license',[]),('category',{}),('use_cases','문자열'),('catalog_approved',1),('runnable',0)]:
            row=repo();row[field]=value
            self.assertEqual(self.snapshot(catalog(row,version=self.store.good['catalog_version']+1 if self.store.good else 1))['repos'],[])

    def test_unapproved_video_is_not_advertised_and_sample_not_invented(self):
        for field,value in [('public_approved',False),('lang','ja'),('valid_until',at())]:
            row=repo();row['video'][field]=value;row['preview']=None
            store=oc.Catalog(lambda *_:(raw(catalog(row)),None),clock=lambda:NOW)
            detail=store.snapshot(row['id'])['repo']
            self.assertIsNone(detail['video']);self.assertIsNone(detail['preview'])
        row=repo();row['video']['status']='ready'
        self.assertEqual(self.snapshot(catalog(row))['repos'],[])
        for url in ['https://evil.example/video','file:///fake/private','https://www.gitbap.com/r/another/fake']:
            row=repo();row['video']['gitbap_url']=url
            store=oc.Catalog(lambda *_:(raw(catalog(row)),None),clock=lambda:NOW)
            self.assertEqual(store.snapshot()['repos'],[])

    def test_text_is_data_not_html_commands_paths_or_secrets(self):
        for value in ['한국어 <script>alert(1)</script>', '한국어 `명령`', '한국어 curl https://fake.example',
                      '한국어 npm install fake', '한국어\npython3 -c fake', '한국어\n$ npm run fake', '한국어 token=FAKE_SECRET', '한국어 /Users/' + 'fake/private', '한국어 sk-FAKE_ONLY']:
            row=repo();row['mild_md']=value
            store=oc.Catalog(lambda *_:(raw(catalog(row)),None),clock=lambda:NOW)
            self.assertEqual(store.snapshot()['repos'],[])
        row=repo();row['mild_md']='한국어 FAKE_BOX_TOKEN_123'
        store=oc.Catalog(lambda *_:(raw(catalog(row)),None),clock=lambda:NOW,
                         redact=lambda value: json.loads(json.dumps(value).replace('FAKE_BOX_TOKEN_123','MASKED')))
        self.assertEqual(store.snapshot()['repos'],[])

    def test_expiry_closes_all_bodies_previews_links_at_boundary(self):
        self.snapshot();self.now=NOW+72*3600
        for ident in [None,'a'*32]:
            result=self.store.snapshot(ident)
            self.assertEqual(result['state'],'expired')
            self.assertNotIn('repo',result)
            self.assertEqual(result['repos'],[])
            self.assertNotIn('https:',json.dumps(result))

    def test_row_review_expiry_and_source_freshness_close_earlier(self):
        row=repo();row['review']['valid_until']=at(1)
        self.snapshot(catalog(row));self.now+=1
        result=self.store.snapshot(row['id'])
        self.assertEqual(result['state'],'unavailable');self.assertIsNone(result['repo'])
        row=repo();row['source']['status_checked_at']=at(-72*3600+2)
        self.now=NOW;self.snapshot(catalog(row,version=2))
        self.assertEqual(self.store.snapshot()['visible_until'],at(2))
        self.now+=2;self.assertEqual(self.store.snapshot()['repos'],[])

    def test_corrupt_oversize_unreadable_and_older_keep_good_without_extending_ttl(self):
        good=self.snapshot(catalog(repo(),version=4))
        for bad in [b'{',b'x'*(oc.MAX_BYTES+1),b'\xff',b'[]',b'{"schema_version":1,"schema_version":2}',b'['*1100]:
            self.document=bad
            result=self.store.snapshot()
            self.assertEqual(result['repos'],good['repos'])
            self.assertEqual(result['valid_until'],at(72*3600))
            self.assertEqual(result['warning'],'load_failed')
        for error in (FileNotFoundError('FAKE_SECRET'),OSError('FAKE_SECRET'),ValueError('FAKE_SECRET')):
            with patch.object(self.store,'read',side_effect=error):
                result=self.store.snapshot();self.assertEqual(result['repos'],good['repos'])
                self.assertNotIn('FAKE_SECRET',json.dumps(result))
        old=catalog(version=3);old['valid_until']=at(3600)
        result=self.snapshot(old);self.assertEqual(result['catalog_version'],4)
        self.assertEqual(result['warning'],'older_version')
        same=catalog(version=4)
        self.assertEqual(self.snapshot(same)['repos'],good['repos'])
        self.now+=72*3600
        self.assertEqual(self.store.snapshot()['state'],'expired')

    def test_invalid_envelope_and_no_good_copy_are_load_failure(self):
        for field,value in [('schema_version',2),('schema_version',True),('catalog_version',True),('catalog_version',-1),
            ('policy_version','unknown'),('generated_at',at(1)),('valid_until',at(72*3600+1)),('repos',{}),
            ('revoked_repo_ids',['invalid']),('revocation_version','1'),('source_commit','bad'),('unknown','FAKE_SECRET')]:
            with self.subTest(field=field):
                doc=catalog(repo());doc[field]=value
                store=oc.Catalog(lambda *_:(raw(doc),None),clock=lambda:NOW)
                self.assertEqual(store.snapshot()['state'],'load_failed')
        doc=catalog(repo(),repo())
        store=oc.Catalog(lambda *_:(raw(doc),None),clock=lambda:NOW)
        self.assertEqual(store.snapshot()['state'],'load_failed')

    def test_signature_hook_rejects_remote_and_closes_even_good_copy(self):
        self.snapshot()
        bad=catalog(repo(),version=2);bad['signature']={'kind':'ed25519','key_id':'fake','value':'FAKE_SECRET'}
        result=self.snapshot(bad)
        self.assertEqual(result['state'],'verification_failed');self.assertEqual(result['repos'],[])
        self.assertNotIn('https:',json.dumps(result))
        self.assertEqual(self.store.good['catalog_version'],1)
        self.document=b'{'
        self.assertEqual(self.store.snapshot()['state'],'verification_failed')
        self.document=raw(catalog(repo()))
        self.assertEqual(self.store.snapshot()['state'],'ready')
        with patch.object(oc,'verify_trusted_bundle',side_effect=oc.SignatureRejected):
            self.assertEqual(self.store.snapshot()['state'],'verification_failed')

    def test_emergency_revocations_apply_before_body_rollback_and_cannot_be_undone(self):
        self.snapshot(catalog(repo(),version=5,revocation=1))
        old=catalog(repo(),version=3,revocation=2,revoked=['a'*32])
        self.assertEqual(self.snapshot(old)['repos'],[])
        for doc in [catalog(repo(),version=4,revocation=1),catalog(repo(),version=6,revocation=3)]:
            self.assertEqual(self.snapshot(doc)['repos'],[])
            self.assertIsNone(self.store.snapshot('a'*32)['repo'])
        self.assertEqual(self.store.revocation_version,3)
        newer=catalog(repo(),repo('e'*32,2),version=7,revocation=2)
        self.assertEqual(self.snapshot(newer)['catalog_version'],6)
        self.assertEqual(self.store.snapshot()['warning'],'older_version')

    def test_valid_empty_replaces_good_and_does_not_extend_old_version(self):
        self.snapshot();result=self.snapshot(catalog(version=2))
        self.assertEqual(result['state'],'empty');self.assertEqual(result['repos'],[])
        self.assertEqual(self.store.snapshot('a'*32)['state'],'unavailable')
        self.assertEqual(self.snapshot(catalog(repo()))['repos'],[])

    def test_l0_reader_cannot_trigger_shell_ai_network_or_user_file_io(self):
        with patch('subprocess.Popen',side_effect=AssertionError('shell')), \
             patch('socket.socket',side_effect=AssertionError('network')), \
             patch('builtins.open',side_effect=AssertionError('file IO')), \
             patch('pathlib.Path.read_text',side_effect=AssertionError('user read')), \
             patch('pathlib.Path.write_text',side_effect=AssertionError('user write')):
            self.assertEqual(self.store.snapshot()['state'],'ready')
            self.assertIsNotNone(self.store.snapshot('a'*32)['repo'])
        self.assertEqual(len(self.read.call_args_list),2)
        self.assertNotIn('import subprocess',(ROOT/'template/lib/opensource_catalog.py').read_text())
        self.assertNotIn('import socket',(ROOT/'template/lib/opensource_catalog.py').read_text())


if __name__=='__main__':unittest.main()
