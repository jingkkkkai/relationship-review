"""Fictional tests of count/source invariants; no user content as fixtures."""
import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from repair_review import validate,statistics,render

def fixture():
 records=[dict(id='R1',speaker_role='self',timestamp='2026-01-01 12:00:00'),dict(id='R2',speaker_role='self',timestamp='2026-01-01 12:01:00'),dict(id='R3',speaker_role='other',timestamp='2026-01-01 12:02:00')]
 archive=dict(records=records,edit_groups=[dict(original_record_id='R1',version_record_ids=['R1','R2'])])
 def entry(i,role,cats,status,source='message',nums=None):return dict(id=i,event_id='E1',actor=role,phase=i,categories=cats,apology_status=status,apology_styles=['direct'] if status=='clear' else ['irony'] if status=='irony' else [],initiative='responded',source_kind=source,record_ids=nums or [],context_record_ids=['R1','R3'] if source=='message' else [],outcome_record_ids=[],evidence_ids=['V1'],summary='Fictional statement <script>',rationale='Fictional contextual reason',outcome='Unknown')
 entries=[entry('A','self',['responsibility','apology'],'clear',nums=['R2']),entry('B','other',[],'irony',nums=['R3']),entry('C','other',['apology'],'clear',source='unsent')]
 review=dict(method='Audited lower bound',scope='Fictional fixture',events=[dict(event_id='E1',note='Unknown is not zero',order_note='No race ranking',status={'self':'confirmed','other':'not_confirmed'})],entries=entries)
 return review,[dict(id='E1')],archive,{'V1'}

class RepairReview(unittest.TestCase):
 def test_overlap_is_one_round_and_non_message_and_irony_excluded(self):
  args=fixture();validate(*args);stats=statistics(args[0])
  self.assertEqual(stats['self']['rounds']['rounds'],1)
  self.assertEqual(stats['self']['responsibility']['rounds'],1)
  self.assertEqual(stats['self']['apology']['rounds'],1)
  self.assertEqual(stats['other']['apology']['rounds'],0)
  self.assertEqual(stats['other']['irony']['rounds'],1)
 def test_edit_versions_cannot_count_twice(self):
  args=list(fixture());e=copy.deepcopy(args[0]['entries'][0]);e['id']='D';e['phase']='New label';e['record_ids']=['R1'];args[0]['entries'].append(e)
  with self.assertRaises(ValueError):validate(*args)
 def test_bad_reference_and_wrong_actor_rejected(self):
  args=list(fixture());args[0]['entries'][0]['record_ids']=['missing']
  with self.assertRaises(ValueError):validate(*args)
  args=list(fixture());args[0]['entries'][0]['actor']='other'
  with self.assertRaises(ValueError):validate(*args)
 def test_unknown_not_promoted_to_confirmed_and_irony_not_apology(self):
  args=list(fixture());args[0]['events'][0]['status']['other']='confirmed'
  with self.assertRaises(ValueError):validate(*args)
  args=list(fixture());args[0]['entries'][1]['categories']=['apology']
  with self.assertRaises(ValueError):validate(*args)
 def test_render_escapes_text_and_links_exact_sources(self):
  args=fixture();summary,events,style=render(*args,{'self':'你','other':'他'})
  self.assertIn('href="#chat-record-R2"',events['E1']);self.assertIn('href="#V1"',events['E1'])
  self.assertNotIn('<script>',events['E1']);self.assertIn('&lt;script&gt;',events['E1'])
  self.assertIn('沒看到',summary)
 def test_generated_anchor_collision_rejected(self):
  args=list(fixture());args[3].add('repair-A')
  with self.assertRaises(ValueError):validate(*args)
  args=list(fixture());args[0]['entries'][0]['id']='summary'
  with self.assertRaises(ValueError):validate(*args)
 def test_full_report_combines_repair_table_event_details_and_mobile_controls(self):
  from test_event_interaction import event_fixture
  from test_edit_history import Tree
  from render_html import render as render_report
  archive,report=event_fixture();review=fixture()[0]
  targets={role:next(r['id'] for r in archive['records'] if r['speaker_role']==role) for role in ('self','other')}
  for e in review['entries']:
   e['evidence_ids']=['D2']
   if e['source_kind']=='message':
    e['record_ids']=[targets[e['actor']]];e['context_record_ids']=list(targets.values())
  report['repair_review']=review;before=copy.deepcopy((archive,report));tree=Tree(render_report(report,archive))
  self.assertEqual(len(tree.classes('repair-summary')),1)
  self.assertEqual(len(tree.classes('repair-event')),1)
  self.assertEqual(len(tree.classes('repair-entry')),3)
  self.assertTrue(tree.by_id('repair-A').under(tree.by_id('E1')))
  self.assertTrue(tree.by_id('mobile-return'));self.assertEqual((archive,report),before)
  ids={n.attrs['id'] for n in tree.root.walk() if 'id' in n.attrs}
  for n in tree.root.walk():
   href=n.attrs.get('href','')
   if href.startswith('#'):self.assertIn(href[1:],ids)

if __name__=='__main__':unittest.main()
