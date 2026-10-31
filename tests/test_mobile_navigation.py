"""Mobile navigation is present in real renderer output, including legacy models."""
import copy
import unittest
from test_event_interaction import event_fixture
from test_edit_history import Tree
from render_html import render

class MobileNavigationTest(unittest.TestCase):
 def test_generated_report_contains_one_set_of_controls_without_data_changes(self):
  archive,report=event_fixture();before=copy.deepcopy((archive,report));markup=render(report,archive);tree=Tree(markup)
  for identity in ('mobile-return','mobile-return-style','mobile-return-script','return-section','return-top'):
   self.assertEqual(sum(n.attrs.get('id')==identity for n in tree.root.walk()),1)
  self.assertIn('hidden',tree.by_id('mobile-return').attrs)
  self.assertEqual(tree.by_id('return-section').tag,'button')
  self.assertEqual(tree.by_id('return-top').tag,'button')
  self.assertIn('回本段',tree.by_id('return-section').text());self.assertIn('回頁首',tree.by_id('return-top').text())
  self.assertEqual((archive,report),before)
 def test_old_models_render_without_repair_statistics(self):
  archive,report=event_fixture();markup=render(report,archive);tree=Tree(markup)
  self.assertEqual(len(tree.classes('repair-summary')),0)
  self.assertTrue(tree.by_id('chat-record-R1'));self.assertTrue(tree.by_id('mobile-return'))
 def test_mobile_control_ids_cannot_collide_with_evidence(self):
  for identity in ('return-top','mobile-return','mobile-return-style','mobile-return-script'):
   with self.subTest(identity=identity):
    archive,report=event_fixture();report['evidence'].append(dict(id=identity,type='未知',text='虛構'))
    with self.assertRaises(ValueError):render(report,archive)

if __name__=='__main__':unittest.main()
