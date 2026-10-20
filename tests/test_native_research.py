import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'template/lib'))
from research import native, settings, engine
from research.run import ResearchError

URL='https://example.org/source'
def candidate():
 return {'checks':[{'requirement':'질문 조건','status':'confirmed','source_ids':[1],'note':'출처에서 확인'}], 'sources':[{'id':1,'title':'원문','url':URL,'published_date':None}],
         'claims':[{'kind':'fact','text':'확인한 사실','source_ids':[1]}],
         'comparison':None,'limitations':'단일 출처','follow_up_questions':['관련 조건은?','다른 사례는?']}
def events():
 return [{'type':'item.completed','item':{'type':'web_search','results':[{'type':'text_result','url':URL,'snippet':'Total lines: 100'}]}}]

class NativeTests(unittest.TestCase):
 def test_routes_follow_setting_at_each_request(self):
  with tempfile.TemporaryDirectory() as home:
   with patch.object(native,'execute',return_value=(candidate(),events())) as execute:
    settings.save(home,'codex','test-model')
    result=engine.research('질문','all',home)
    self.assertEqual(execute.call_args.args[:2],('codex','test-model'))
    self.assertEqual(result['metrics']['provider'],'codex-native')
    settings.save(home,'claude')
    with patch.object(native,'validate_result',return_value=(candidate()['sources'],{'claims':candidate()['claims'],'limitations':''},1)):
     engine.research('질문','all',home)
    self.assertEqual(execute.call_args.args[:2],('claude',''))
 def test_unobserved_source_rejected_even_if_final_mentions_url(self):
  with self.assertRaises(ResearchError):native.validate_result(candidate(),[{'type':'item.completed','item':{'type':'agent_message','text':URL}}],'codex')
  c=candidate();c['sources'][0]['url']='https://example.org/invented'
  with self.assertRaises(ResearchError):native.validate_result(c,events(),'codex')
 def test_uncited_fact_and_table_cell_rejected(self):
  c=candidate();c['claims'][0]['source_ids']=[]
  with self.assertRaises(ResearchError):native.validate_result(c,events(),'codex')
  c=candidate();c['comparison']={'headers':['항목','대상'],'rows':[{'label':'조건','cells':[{'kind':'fact','text':'사실','source_ids':[9]}]}]}
  with self.assertRaises(ResearchError):native.validate_result(c,events(),'codex')
 def test_missing_eligibility_is_visible_before_summary(self):
  c=candidate();c['checks'][0].update(status='unconfirmed',note='두 번째 사례 연령 미확인')
  _,answer,_=native.validate_result(c,events(),'codex')
  self.assertEqual(answer['claims'][0]['kind'],'uncertain')
  self.assertEqual(answer['verification']['status'],'partial')
  self.assertIn('질문 조건',answer['claims'][0]['text'])
  self.assertNotIn('확인한 사실',[v['text'] for v in answer['claims']])
 def test_confirmed_requirement_requires_observed_source(self):
  c=candidate();c['checks'][0]['source_ids']=[]
  with self.assertRaises(ResearchError):native.validate_result(c,events(),'codex')
 def test_duplicate_source_ids_rejected(self):
  c=candidate();c['sources']*=2
  with self.assertRaises(ResearchError):native.validate_result(c,events(),'codex')
 def test_snippet_never_marked_read(self):
  e=events();e[0]['item']['results'][0]['snippet']='검색 발췌문'
  sources,_,_=native.validate_result(candidate(),e,'codex')
  self.assertEqual(sources[0]['read_status'],'snippet')
 def test_failed_claude_fetch_not_evidence(self):
  e=[{'type':'assistant','message':{'content':[{'type':'tool_use','id':'1','name':'WebFetch','input':{'url':URL}}]}},
     {'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'1','is_error':True,'content':'failed'}]}}]
  self.assertEqual(native.evidence(e,'claude'),({},0))
 def test_claude_search_links_only(self):
  e=[{'type':'assistant','message':{'content':[{'type':'tool_use','id':'1','name':'WebSearch','input':{'query':'test'}}]}},
     {'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'1','content':'Links: '+json.dumps([{'url':URL}])+'\nhttps://example.org/unrelated'}]}}]
  seen,count=native.evidence(e,'claude');self.assertEqual(count,1);self.assertEqual(seen,{URL:False})
 def test_fallback_keeps_selected_model_and_records_tavily(self):
  with tempfile.TemporaryDirectory() as home:
   settings.save(home,'codex')
   supplement=[{'id':1,'title':'원문','url':URL,'content':'자료','read_status':'read'}]
   with patch.object(native,'execute',side_effect=[ResearchError('검색 실패'),(candidate(),[])]), patch.object(native.shutil,'which',return_value='/bin/tool'), patch('research.multi_source.tavily',return_value=supplement):
    result=engine.research('질문','all',home)
   self.assertEqual(result['coverage']['attempts'],['codex-native','tavily-supplement'])
   self.assertEqual(result['sources'][0]['provider'],'tavily')
   self.assertEqual(result['metrics']['provider'],'codex-native')
 def test_invalid_settings_do_not_silently_change_provider(self):
  with tempfile.TemporaryDirectory() as home:
   p=Path(home)/'state';p.mkdir();(p/'ai-settings.json').write_text('{"provider":"other"}')
   with self.assertRaises(ValueError):settings.load(home)
 def test_sandbox_rejected_before_native_execution(self):
  with tempfile.TemporaryDirectory() as home:
   p=Path(home)/'state';p.mkdir();(p/'sandbox').touch()
   with patch.object(native,'execute') as execute:
    with self.assertRaises(ResearchError):engine.research('질문','all',home)
    execute.assert_not_called()

if __name__=='__main__':unittest.main()
