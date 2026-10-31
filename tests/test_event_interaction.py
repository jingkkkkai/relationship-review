"""Event reactions retain traceability, local caveats and old report compatibility."""
import copy
import unittest
from test_stage_states import comparison_fixture
from test_edit_history import Tree
from render_html import render


def event_fixture():
    archive, report = comparison_fixture()
    groups = {
        'self': {'summary': '', 'items': [dict(title='先確認時間', text='你先核對原本的時間，再確認他方不方便。', evidence_ids=['D2'])]},
        'other': {'summary': '若補述屬實，回應也可能與當天趕路有關；紀錄未包含通話內容。', 'items': [dict(title='確認改動', text='他問了改動後的安排，讓你們有機會重新確認。', evidence_ids=['D2', 'S1'])]},
    }
    report['events'] = [dict(id='E1', date='2026/01/01', title='虛構時間確認', summary='僅供測試的互動。', sections=[], interaction=groups)]
    return archive, report


class EventInteractionTest(unittest.TestCase):
    def setUp(self): self.archive, self.report = event_fixture()
    def markup(self): return render(self.report, self.archive)

    def test_reactions_and_local_limits_have_traceable_evidence(self):
        tree = Tree(self.markup()); event = tree.by_id('E1')
        self.assertEqual(len([node for node in event.walk() if node.has_class('event-interaction-group')]), 2)
        self.assertIn('你先核對原本的時間', event.text())
        self.assertIn('若補述屬實', event.text())
        self.assertIn('紀錄未包含通話內容', event.text())
        links = [node.attrs.get('href') for node in event.walk() if node.tag == 'a']
        self.assertIn('#D2', links); self.assertIn('#S1', links)
        self.assertNotIn('不會因為一次互動就斷定', event.text())
        self.assertEqual(tree.root.text().count('不會因為一次互動就斷定'), 1)

    def test_old_role_groups_reuse_same_interface_without_mutation(self):
        expected = self.markup()
        event = self.report['events'][0]
        event['psychology'] = event.pop('interaction')
        before = copy.deepcopy(self.report)
        self.assertEqual(self.markup(), expected)
        self.assertEqual(self.report, before)

    def test_conflicting_new_and_legacy_groups_are_not_silently_selected(self):
        event = self.report['events'][0]
        event['psychology'] = copy.deepcopy(event['interaction'])
        self.markup()
        event['psychology']['self']['summary'] = '不同的舊文字'
        with self.assertRaises(ValueError): self.markup()

    def test_incomplete_observation_or_unknown_evidence_rejected(self):
        for key, value in [('title', ''), ('text', ''), ('evidence_ids', []), ('evidence_ids', ['MISSING'])]:
            with self.subTest(key=key, value=value):
                bad = copy.deepcopy(self.report)
                bad['events'][0]['interaction']['self']['items'][0][key] = value
                with self.assertRaises(ValueError): render(bad, self.archive)
        self.report['events'][0]['interaction'].pop('other')
        with self.assertRaises(ValueError): self.markup()

    def test_concrete_gap_allowed_but_empty_group_rejected(self):
        group = self.report['events'][0]['interaction']['self']
        group['items'] = []
        with self.assertRaises(ValueError): self.markup()
        group['summary'] = '這次只有他傳的訊息，沒有你的回應。'
        self.assertIn(group['summary'], Tree(self.markup()).by_id('E1').text())

    def test_names_prose_safety_and_all_reference_targets(self):
        names = dict(self='甲', other='乙', explicitly_requested=True)
        self.archive['display_names'] = self.report['display_names'] = names
        self.report['events'][0]['interaction']['self']['items'][0]['text'] = '<script>bad()</script> test@example.test 0900-000-000'
        markup = self.markup(); tree = Tree(markup)
        self.assertIn('甲的反應', tree.by_id('E1').text())
        self.assertNotIn('<script>bad()</script>', markup)
        self.assertNotIn('test@example.test', markup); self.assertNotIn('0900-000-000', markup)
        ids = [node.attrs['id'] for node in tree.root.walk() if 'id' in node.attrs]
        self.assertEqual(len(ids), len(set(ids)))
        for node in tree.root.walk():
            href = node.attrs.get('href', '')
            if href.startswith('#'): self.assertIn(href[1:], ids)


if __name__ == '__main__': unittest.main()
