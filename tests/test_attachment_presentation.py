"""Synthetic regression tests: preserve attachments while redacting dialogue text.

Run with: python3 -B -m unittest discover -s tests -v
No private conversations, external requests or third-party libraries are used.
"""
import base64
import copy
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from presentation import Materials, link, linked_text, safe_url
from render_html import render


class Tags(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.items = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.items.append((tag, dict(attrs)))

    def of(self, kind):
        return [attrs for tag, attrs in self.items if tag == kind]


THREADS = 'https://www.threads.com/@fictional.user/post/DEMO?x=1&y=2'
REEL = 'https://www.instagram.com/0900000000/reel/DEMO/?igsh=example'
CONTACT = 'example.person@example.test 0900-000-000'
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jV4sAAAAASUVORK5CYII=')


class AttachmentPresentationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'sample.png').write_bytes(PNG)
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b'\0\0' * 80)
        self.audio = buffer.getvalue()
        (self.root / 'sample.wav').write_bytes(self.audio)
        (self.root / 'note.txt').write_bytes(CONTACT.encode())

    def test_account_paths_and_encoded_handles_keep_exact_targets(self):
        for url, platform, label in (
            (THREADS, 'threads_post', '(threads)'),
            (THREADS.replace('threads.com', 'threads.net'), 'threads_post', '(threads)'),
            (THREADS.replace('@fictional.user', '%40fictional.user'), 'threads_post', '(threads)'),
            (REEL, 'reel', '(reels)'),
            (REEL.replace('/0900000000/', '/@fictional.user/'), 'reel', '(reels)'),
        ):
            with self.subTest(url=url):
                self.assertEqual(safe_url(url, platform), url)
                markup = link(url, label, platform, attachment=True)
                self.assertEqual(Tags(markup).of('a')[0]['href'], url)
                self.assertIn('>' + label + '</a>', markup)

    def test_plain_social_link_does_not_misread_handle_or_post_id(self):
        for url in (THREADS, REEL):
            with self.subTest(url=url):
                markup = linked_text(url)
                self.assertEqual(Tags(markup).of('a')[0]['href'], url)
                self.assertNotIn('***', markup)

    def test_attachment_urls_keep_contacts_and_signed_parameters(self):
        url = 'https://cdn.example.test/0900000000.png?owner=example%40example.test&token=synthetic-signature'
        markup = Materials().render({'type': 'image', 'url': url})
        self.assertEqual(Tags(markup).of('a')[0]['href'], url)
        # The same URL in ordinary prose is still covered by text privacy rules.
        self.assertFalse(Tags(linked_text(url)).of('a'))

    def test_text_and_text_links_are_still_redacted(self):
        markup = linked_text(CONTACT + ' https://example.test/?email=example%40example.test')
        self.assertNotIn('example.person@example.test', markup)
        self.assertNotIn('0900-000-000', markup)
        self.assertFalse(Tags(markup).of('a'))
        self.assertIn('***', markup)

    def test_image_and_voice_need_no_privacy_flag(self):
        for flag in (None, False, True):
            for kind, path, mime, expected in (
                ('image', 'sample.png', 'image/png', PNG),
                ('audio', 'sample.wav', 'audio/wav', self.audio),
            ):
                with self.subTest(flag=flag, kind=kind):
                    item = {'type': kind, 'path': path, 'mime': mime}
                    if flag is not None:
                        item['privacy_reviewed'] = flag
                    markup = Materials(self.root).render(item)
                    tag = 'img' if kind == 'image' else 'audio'
                    attrs = Tags(markup).of(tag)[0]
                    self.assertEqual(base64.b64decode(attrs['src'].split(',', 1)[1]), expected)
                    self.assertNotIn('autoplay', attrs)
                    if kind == 'audio':
                        self.assertIn('controls', attrs)

    def test_text_attachment_preserves_original_bytes(self):
        markup = Materials(self.root).render({'type': 'file', 'path': 'note.txt', 'mime': 'text/plain'})
        href = Tags(markup).of('a')[0]['href']
        self.assertEqual(base64.b64decode(href.split(',', 1)[1]), CONTACT.encode())

    def test_basic_url_validation_remains(self):
        for url in ('javascript:alert(1)', 'file:///tmp/example', 'https://user:pass@example.test/a', 'https://example.test:invalid/a', 'https://example.test/\\evil', 'https://example.test/\n'):
            with self.subTest(url=url):
                self.assertIsNone(safe_url(url))
        self.assertIsNone(safe_url('https://threads.com.example.test/@user/post/id', 'threads_post'))
        self.assertIsNone(safe_url('https://example.test/reel/id', 'reel'))
        self.assertEqual(Tags(link('https://example.test/"<script>', '(附件)', attachment=True)).of('script'), [])

    def test_path_and_type_checks_remain_even_with_legacy_false(self):
        items = [
            {'type': 'image', 'path': '../outside.png', 'mime': 'image/png'},
            {'type': 'image', 'path': str(self.root / 'sample.png'), 'mime': 'image/png'},
            {'type': 'image', 'path': 'note.txt', 'mime': 'image/png'},
            {'type': 'image', 'path': 'sample.png', 'mime': 'image/svg+xml'},
        ]
        for item in items:
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    Materials(self.root).render(dict(item, privacy_reviewed=False))
        missing = Materials(self.root).render({'type': 'image', 'path': 'missing.png', 'mime': 'image/png'})
        self.assertIn('找不到原檔', missing)

    def test_full_report_keeps_media_shares_and_masked_quotes(self):
        records = []
        for number in range(1, 6):
            records.append({'id': f'R{number}', 'source_id': 'demo', 'position': number, 'timestamp': f'2026/01/01 12:0{number}', 'sender': 'fictional', 'speaker_role': 'self' if number % 2 else 'other', 'kind': 'message', 'text': '', 'source': f'fictional record {number}'})
        records[0]['text'] = CONTACT
        records[1].update(display_type='reel', share_url=REEL, comment=CONTACT)
        records[2].update(display_type='threads_post', share_url=THREADS)
        records[3].update(text='Synthetic attachments', media=[{'type': 'image', 'path': 'sample.png', 'mime': 'image/png', 'privacy_reviewed': False}, {'type': 'audio', 'path': 'sample.wav', 'mime': 'audio/wav'}], reply={'source_verified': True, 'record_id': 'R1'})
        records[4].update(text='Synthetic text file', media=[{'type': 'file', 'path': 'note.txt', 'mime': 'text/plain'}])
        audit = {'sources': [{'source_id': 'demo', 'source_kind': 'message', 'record_count': 5, 'reviewed_ranges': [{'start': 1, 'end': 5, 'status': 'read', 'note': 'Synthetic display fixture, not a relationship assessment.'}]}], 'attachments': []}
        archive = {'reading_audit': audit, 'records': records, 'segments': [{'id': 'C1', 'date': '2026/01/01', 'title': 'Synthetic fixture', 'categories': ['氣氛不明'], 'record_ids': [r['id'] for r in records]}]}
        stage = dict(title='Synthetic phase', period='2026/01/01', summary='No real people.', segment_ids=['C1'], **{key: {'text': 'Insufficient data; synthetic test only.', 'evidence_ids': []} for key in ('self_needs', 'other_needs', 'self_improvements', 'other_improvements')})
        stage['states'] = {role: {'current': {'text': '介面測試，不作狀態判斷。', 'evidence_ids': []}, 'change': {'status': 'baseline', 'text': '起始觀察，無前階段。', 'evidence_ids': []}, 'exceptions': {'text': '僅為虛構測試，未評估例外。', 'evidence_ids': []}} for role in ('self', 'other')}
        stage['state_context'] = {'text': '介面測試，無法判斷影響因素。', 'evidence_ids': []}
        report = {'reading_audit': audit, 'conversation_index': {'section_id': 'conversation-review', 'segment_ids': ['C1']}, 'title': 'Synthetic test', 'scope': 'Fictional data only', 'coverage': 'Display test', 'takeaways': [], 'events': [], 'overall': [], 'evidence': [], 'stage_review': [stage], 'concepts': {key: {'summary': 'Synthetic test; no assessment.', 'items': []} for key in ('self', 'other', 'shared')}}
        markup = render(report, archive, materials_root=self.root)
        tags = Tags(markup)
        self.assertIn(THREADS, [item['href'] for item in tags.of('a')])
        self.assertIn(REEL, [item['href'] for item in tags.of('a')])
        self.assertEqual(len(tags.of('img')), 1)
        self.assertEqual(len(tags.of('audio')), 1)
        self.assertNotIn('example.person@example.test', markup)
        self.assertNotIn('0900-000-000', markup)
        self.assertIn('#chat-record-R1', [item['href'] for item in tags.of('a')])
        ids = [attrs['id'] for _, attrs in tags.items if 'id' in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(href[1:] in ids for href in [item['href'] for item in tags.of('a')] if href.startswith('#')))
        for kind in ('img', 'audio'):
            self.assertTrue(all(item['src'].startswith('data:') for item in tags.of(kind)))
        self.assertIn('圖片、語音等附件和分享連結保持原樣', markup)


if __name__ == '__main__':
    unittest.main()
