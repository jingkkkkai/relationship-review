"""Fictional edit-history cases: one bubble, original time, no lost snapshots."""
import copy
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from render_archive import render as render_conversations, validate_archive
from render_html import render


def fixture():
    content = [
        ('2026/01/01 18:00', 'self', '明天十二點，在公園入口見。'),
        ('2026/01/01 18:01', 'other', '好，我照十二點安排。'),
        ('2026/01/01 18:03', 'self', '明天下午一點，在公園入口見。'),
        ('2026/01/01 18:04', 'other', '你原本寫十二點，是改一點了嗎？'),
        ('2026/01/02 09:00', 'self', '今天下午一點，在公園北門見。'),
        ('2026/01/02 09:01', 'other', '收到，北門一點。'),
    ]
    records = [dict(id=f'R{i}', source_id='synthetic', position=i, timestamp=stamp, sender=role, speaker_role=role, kind='message', text=text, source=f'虛構匯出第 {i} 筆') for i, (stamp, role, text) in enumerate(content, 1)]
    records[2]['version_status'] = records[4]['version_status'] = 'edited'
    records[3]['reply'] = {'source_verified': True, 'record_id': 'R1'}
    records[5]['reply'] = {'source_verified': True, 'record_id': 'R5'}
    audit = {'sources': [{'source_id': 'synthetic', 'source_kind': 'message', 'record_count': 6, 'reviewed_ranges': [{'start': 1, 'end': 6, 'status': 'read', 'note': '全部為虛構的三版本／回覆顯示案例，並非真人分析。'}]}], 'attachments': []}
    segments = [dict(id=f'C{i}', title=title, date=day, categories=[category], record_ids=ids) for i, (title, day, category, ids) in enumerate([
        ('原始邀約與回覆', '2026/01/01', '日常與照顧', ['R1', 'R2']),
        ('同一天修改時間並釐清', '2026/01/01', '討論與磨合', ['R3', 'R4']),
        ('隔天修改地點與確認', '2026/01/02', '討論與磨合', ['R5', 'R6']),
    ], 1)]
    archive = dict(reading_audit=audit, records=records, segments=segments, edit_groups=[{'original_record_id': 'R1', 'version_record_ids': ['R1', 'R3', 'R5'], 'source_verified': True, 'source': '虛構來源明確標示三筆皆為 M001 的原始／第一次／第二次版本。'}])
    stage = dict(title='同一則訊息，保留修改過程', period='2026/01/01–01/02', summary='最新版留在原訊息的位置；較晚片段可跳回編輯紀錄。', segment_ids=['C1', 'C2', 'C3'], **{key: {'text': '這份只示範介面，不分析真實需求或責任。', 'evidence_ids': []} for key in ('self_needs', 'other_needs', 'self_improvements', 'other_improvements')})
    stage['states'] = {role: {'current': {'text': '介面測試，不作狀態判斷。', 'evidence_ids': []}, 'change': {'status': 'baseline', 'text': '起始觀察，無前階段。', 'evidence_ids': []}, 'exceptions': {'text': '僅為虛構測試，未評估例外。', 'evidence_ids': []}} for role in ('self', 'other')}
    stage['state_context'] = {'text': '介面測試，無法判斷影響因素。', 'evidence_ids': []}
    report = dict(reading_audit=audit, conversation_index={'section_id': 'conversation-review', 'segment_ids': ['C1', 'C2', 'C3']}, title='訊息編輯｜虛構小量示範', scope='六筆虛構紀錄：一則訊息的原文、兩次修改，以及三則回覆；沒有真人資料。', coverage='全部虛構紀錄已核對。此頁僅供確認編輯顯示，不是關係評估。', takeaways=['下方「完整對話」的第一段：主氣泡時間是原始的 18:00，顯示隔天修改後的最新版。', '點「編輯紀錄」可看原文與第一次修改；第二段引用仍保留對方所回覆的原文。'], stage_review=[stage], concepts={role: {'summary': '此為介面示範，不提供心理學判斷。', 'items': []} for role in ('self', 'other', 'shared')}, events=[], overall=[], evidence=[])
    return archive, report


class Node:
    def __init__(self, tag='', attrs=None, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs or []), parent, []
    def text(self):
        return ''.join(child if isinstance(child, str) else child.text() for child in self.children)
    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()
    def has_class(self, name):
        return name in self.attrs.get('class', '').split()
    def under(self, node):
        current = self.parent
        while current:
            if current is node:
                return True
            current = current.parent
        return False


class Tree(HTMLParser):
    def __init__(self, markup):
        super().__init__();self.root=Node();self.current=self.root;self.feed(markup)
    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current);self.current.children.append(node)
        if tag not in ('img','input','meta','br','hr','source','link'):
            self.current=node
    def handle_endtag(self, tag):
        node=self.current
        while node.parent:
            if node.tag==tag:
                self.current=node.parent;return
            node=node.parent
    def handle_data(self, data):self.current.children.append(data)
    def by_id(self, identity):return next(node for node in self.root.walk() if node.attrs.get('id')==identity)
    def classes(self, name):return [node for node in self.root.walk() if node.has_class(name)]


class EditHistoryTest(unittest.TestCase):
    def setUp(self):self.archive,self.report=fixture()
    def markup(self):return render(self.report,self.archive)
    def reject(self, archive):
        with self.assertRaises(ValueError):validate_archive(archive)

    def test_one_bubble_latest_visible_history_closed(self):
        tree=Tree(self.markup())
        self.assertEqual(len(tree.classes('message')),4)
        group=tree.by_id('chat-message-R1');latest=tree.by_id('chat-record-R5');history=tree.by_id('chat-edits-R1')
        self.assertTrue(latest.under(group));self.assertFalse(latest.under(history))
        self.assertEqual(latest.text(),'今天下午一點，在公園北門見。')
        self.assertNotIn('open',history.attrs)
        self.assertTrue(tree.by_id('chat-record-R1').under(history))
        self.assertTrue(tree.by_id('chat-record-R3').under(history))
        self.assertEqual([node.attrs.get('id') for node in history.walk() if node.has_class('edit-version')],['chat-record-R1','chat-record-R3'])

    def test_primary_time_and_position_are_original(self):
        tree=Tree(self.markup());group=tree.by_id('chat-message-R1')
        self.assertTrue(group.under(tree.by_id('chat-segment-C1')))
        main_meta=next(node for node in group.walk() if node.has_class('meta'))
        self.assertEqual(main_meta.text(),'你 · 18:00')
        self.assertLess(self.markup().index('id="chat-message-R1"'),self.markup().index('id="chat-record-R2"'))
        self.assertEqual(len([node for node in tree.by_id('chat-segment-C1').walk() if node.has_class('chat-day')]),1)

    def test_cross_segment_updates_link_to_same_history(self):
        tree=Tree(self.markup())
        for sid in ('C2','C3'):
            segment=tree.by_id('chat-segment-'+sid)
            links=[node.attrs.get('href') for node in segment.walk() if node.tag=='a']
            self.assertIn('#chat-edits-R1',links)
            self.assertFalse(any(node.has_class('latest-version') for node in segment.walk()))

    def test_all_snapshots_anchors_and_coverage_preserved(self):
        before=copy.deepcopy(self.archive);markup=self.markup();tree=Tree(markup)
        ids=[node.attrs['id'] for node in tree.root.walk() if 'id' in node.attrs]
        self.assertEqual(len(ids),len(set(ids)))
        for record in self.archive['records']:
            self.assertEqual(ids.count('chat-record-'+record['id']),1)
        for node in tree.root.walk():
            href=node.attrs.get('href','')
            if href.startswith('#'):self.assertIn(href[1:],ids)
        self.assertEqual(self.archive,before)
        self.assertIn('共 6 筆紀錄',markup)

    def test_reply_to_old_version_keeps_old_text(self):
        tree=Tree(self.markup());reply=tree.classes('reply')[0]
        self.assertIn('明天十二點，在公園入口見。',reply.text())
        self.assertNotIn('今天下午一點',reply.text())
        self.assertEqual(next(node.attrs['href'] for node in reply.walk() if node.tag=='a'),'#chat-record-R1')

    def test_no_inference_from_similar_words_or_edited_flag(self):
        self.archive.pop('edit_groups')
        tree=Tree(self.markup())
        self.assertEqual(len(tree.classes('message')),6)
        self.assertFalse(tree.classes('edit-history'))
        self.assertIn('匯出檔沒有舊版本',tree.root.text())

    def test_unknown_original_time_is_not_replaced_by_edit_time(self):
        self.archive['records'][0]['timestamp']='原始時間不明'
        tree=Tree(self.markup());group=tree.by_id('chat-message-R1')
        self.assertEqual(next(node for node in group.walk() if node.has_class('meta')).text(),'你 · 原始時間不明')

    def test_history_text_redacted_and_share_urls_preserved(self):
        self.archive['records'][0]['text']='example@example.test 0900-000-000 <script>bad()</script>'
        self.archive['records'][2].update(display_type='threads_post',share_url='https://www.threads.com/@fictional.user/post/DEMO')
        markup=self.markup();tree=Tree(markup)
        self.assertNotIn('example@example.test',markup);self.assertNotIn('0900-000-000',markup)
        self.assertNotIn('<script>bad()</script>',markup)
        self.assertIn('https://www.threads.com/@fictional.user/post/DEMO',[node.attrs.get('href') for node in tree.root.walk()])

    def test_missing_or_unverified_source_rejected(self):
        for key,value in [('source_verified',False),('source','')]:
            bad=copy.deepcopy(self.archive);bad['edit_groups'][0][key]=value;self.reject(bad)

    def test_nonexistent_duplicate_overlap_and_wrong_role_rejected(self):
        for versions in (['R1','MISSING'],['R1','R3','R3'],['R1','R2']):
            bad=copy.deepcopy(self.archive);bad['edit_groups'][0]['version_record_ids']=versions;self.reject(bad)
        bad=copy.deepcopy(self.archive);bad['edit_groups'].append(copy.deepcopy(bad['edit_groups'][0]));self.reject(bad)

    def test_reversed_version_order_or_wrong_original_rejected(self):
        bad=copy.deepcopy(self.archive);bad['edit_groups'][0]['version_record_ids']=['R1','R5','R3'];self.reject(bad)
        bad=copy.deepcopy(self.archive);bad['edit_groups'][0]['original_record_id']='R3';self.reject(bad)

    def test_missing_raw_record_still_fails_reading_coverage(self):
        bad=copy.deepcopy(self.archive);bad['records'].pop();self.reject(bad)

    def test_new_history_anchor_collision_rejected(self):
        self.report['events']=[dict(id='chat-edits-R1',title='invalid',date='unknown',summary='',sections=[])]
        with self.assertRaises(ValueError):self.markup()


if __name__=='__main__':unittest.main()
