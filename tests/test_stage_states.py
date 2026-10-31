"""Verify explicit stage states and two-sided comparisons using fictional data."""
import copy
import unittest
from test_edit_history import fixture, Tree
from render_html import render


def comparison_fixture():
    archive, report = fixture()
    first = copy.deepcopy(report['stage_review'][0])
    second = copy.deepcopy(first)
    first.update(title='虛構起始階段', segment_ids=['C1'])
    second.update(title='虛構後續階段', segment_ids=['C2', 'C3'])
    report['evidence'] = [
        dict(id='D1', type='訊息紀錄', source='虛構來源前段', text='前階段測試依據。', context_segment_ids=['C1']),
        dict(id='D2', type='訊息紀錄', source='虛構來源後段', text='後階段測試依據。', context_segment_ids=['C2']),
        dict(id='S1', type='事後回憶', source='虛構補述', text='僅用來測試來源層級，不是獨立證實。'),
    ]
    for role in ('self', 'other'):
        first['states'][role]['current'] = dict(text='虛構起始觀察。', evidence_ids=['D1'])
        second['states'][role] = {
            'current': dict(text='虛構當下觀察，不推斷人格。', evidence_ids=['D2']),
            'change': dict(status='compared', text='比對前後的虛構片段，未觀察到明確變化。', evidence_ids=['D1', 'D2']),
            'exceptions': dict(text='仍保留後期能確認、修復的例子與未知。', evidence_ids=['D2']),
        }
    second['state_context'] = dict(text='可能因素只是待探索的解釋，測試資料不足以支持因果。', evidence_ids=[])
    report['stage_review'] = [first, second]
    return archive, report


class StageStateTest(unittest.TestCase):
    def setUp(self): self.archive, self.report = comparison_fixture()
    def render(self): return render(self.report, self.archive)
    def reject(self, report):
        with self.assertRaises(ValueError): render(report, self.archive)

    def test_states_current_comparison_and_exceptions_visible_by_role(self):
        markup = self.render(); tree = Tree(markup)
        self.assertEqual(len(tree.classes('stage-person')), 4)
        headings = [node.text() for node in tree.root.walk() if node.tag == 'summary']
        self.assertEqual(headings.count('起始觀察'), 2)
        self.assertEqual(headings.count('和前一階段相比'), 2)
        self.assertEqual(headings.count('例外、修復和還不確定的地方'), 4)
        self.assertEqual(headings.count('可能的原因'), 2)
        self.assertIn('未觀察到明確變化', markup)
        self.assertIn('仍保留後期能確認、修復的例子與未知', markup)

    def test_compared_needs_message_evidence_from_both_stages(self):
        for references in ([], ['D1'], ['D2'], ['S1'], ['D1', 'S1']):
            with self.subTest(references=references):
                bad = copy.deepcopy(self.report)
                bad['stage_review'][1]['states']['self']['change']['evidence_ids'] = references
                self.reject(bad)

    def test_first_stage_cannot_invent_previous_state(self):
        bad = copy.deepcopy(self.report)
        bad['stage_review'][0]['states']['self']['change'].update(status='compared', evidence_ids=['D1', 'D2'])
        self.reject(bad)
        bad = copy.deepcopy(self.report)
        bad['stage_review'][1]['states']['self']['change']['status'] = 'baseline'
        self.reject(bad)

    def test_insufficient_comparison_can_have_no_references(self):
        state = self.report['stage_review'][1]['states']['self']
        state['change'] = dict(status='insufficient', text='缺少相近情境的對照，不能確認趨勢。', evidence_ids=[])
        self.assertIn('缺少相近情境的對照，不能確認趨勢。', self.render())

    def test_missing_role_state_or_context_is_not_silently_filled(self):
        for path in (('states',), ('state_context',), ('states', 'other'), ('states', 'self', 'current'), ('states', 'self', 'exceptions')):
            with self.subTest(path=path):
                bad = copy.deepcopy(self.report); target = bad['stage_review'][1]
                for key in path[:-1]: target = target[key]
                target.pop(path[-1]); self.reject(bad)

    def test_unknown_reference_or_missing_explanation_rejected(self):
        for field in ('current', 'change', 'exceptions'):
            bad = copy.deepcopy(self.report)
            bad['stage_review'][1]['states']['self'][field]['evidence_ids'] = ['MISSING']
            self.reject(bad)
        bad = copy.deepcopy(self.report); bad['stage_review'][1]['state_context']['text'] = ''; self.reject(bad)

    def test_all_reference_links_valid_and_input_unchanged(self):
        before = copy.deepcopy((self.archive, self.report)); tree = Tree(self.render())
        ids = [node.attrs['id'] for node in tree.root.walk() if 'id' in node.attrs]
        self.assertEqual(len(ids), len(set(ids)))
        for node in tree.root.walk():
            href = node.attrs.get('href', '')
            if href.startswith('#'): self.assertIn(href[1:], ids)
        self.assertEqual((self.archive, self.report), before)

    def test_state_prose_escaped_and_contact_masked(self):
        self.report['stage_review'][1]['states']['self']['current']['text'] = '<script>bad()</script> test@example.test 0900-000-000'
        markup = self.render()
        self.assertNotIn('<script>bad()</script>', markup)
        self.assertNotIn('test@example.test', markup)
        self.assertNotIn('0900-000-000', markup)

    def test_explicit_names_apply_to_both_state_cards(self):
        names = dict(self='甲', other='乙', explicitly_requested=True)
        self.archive['display_names'] = self.report['display_names'] = names
        markup = self.render()
        self.assertIn('甲這時的狀態', markup)
        self.assertIn('乙這時的狀態', markup)


if __name__ == '__main__': unittest.main()
