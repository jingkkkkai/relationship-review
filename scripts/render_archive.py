#!/usr/bin/env python3
"""Validate classified records and build the embedded conversation section."""
import argparse
import html
import json
from pathlib import Path
import re
from render_html import validate_reading
from presentation import esc, attr, link, linked_text, Materials

CATEGORIES = ('開心與親密', '日常與照顧', '討論與磨合', '緊張與爭執', '氣氛不明')
DISPLAY_TYPES = {'text', 'reaction', 'reel', 'threads_post', 'image', 'video', 'audio', 'file', 'sticker', 'call', 'system', 'unsent', 'share', 'other'}
KIND_TYPES = {'message': 'text', 'text': 'text', 'reaction': 'reaction', 'reel': 'reel', 'threads_post': 'threads_post', 'notification': 'system', 'system': 'system', 'image': 'image', 'photo': 'image', 'video': 'video', 'audio': 'audio', 'file': 'file', 'sticker': 'sticker', 'call': 'call', 'unsent': 'unsent', 'share': 'share'}
MARKERS = {'reel': '(reels)', 'threads_post': '(threads)', 'image': '(圖片)', 'video': '(影片)', 'audio': '(語音)', 'file': '(附件)', 'sticker': '(貼圖)', 'call': '(通話)', 'unsent': '(訊息已收回)', 'share': '(分享)', 'other': '(其他紀錄)'}
EMOJI = re.compile(r'(?:[\U0001F1E6-\U0001F1FF]{2}|[#*0-9]\uFE0F?\u20E3|[\u2300-\u23FF\u2600-\u27BF\U0001F000-\U0001FAFF][\uFE0E\uFE0F\U0001F3FB-\U0001F3FF]*(?:\u200D[\u2300-\u23FF\u2600-\u27BF\U0001F000-\U0001FAFF][\uFE0E\uFE0F\U0001F3FB-\U0001F3FF]*)*)')


def display_type(record):
    value = record.get('display_type', KIND_TYPES.get(record['kind']))
    if value not in DISPLAY_TYPES:
        raise ValueError('請將紀錄轉成規定的 display_type，不直接顯示原始物件')
    return value


def emoji(value):
    if not isinstance(value, str) or not EMOJI.fullmatch(value):
        raise ValueError('reaction 必須是已核對的單一 emoji，不接受 JSON 或一般文字')
    return value


def visible_body(record):
    kind = display_type(record)
    if kind == 'reaction':
        return '(' + emoji(record.get('reaction_emoji')) + ')'
    if kind == 'text':
        return record['text']
    if kind == 'system':
        value = record.get('system_text')
        if value is None:
            return '(系統通知)'
        if not isinstance(value, str):
            raise ValueError('system_text 須為白話文字')
        return value
    comment = record.get('comment', '')
    if not isinstance(comment, str):
        raise ValueError('comment 須為使用者實際附上的文字')
    return MARKERS[kind] + ('\n' + comment if comment else '')


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]+', value)


DEFAULT_NAMES = {'self': '你', 'other': '他'}


def pronoun_note(names):
    """Top-of-report legend; chat originals keep their own 我／你."""
    return f'稱呼說明：這份報告裡的「{names["self"]}」是匯出這份對話、閱讀報告的人，「{names["other"]}」是對話裡的另一個人。聊天原文照原樣呈現，裡面的「我」「你」不改。'


def display_names(data):
    names = dict(DEFAULT_NAMES)
    config = data.get('display_names')
    if config is None:
        return names
    if not isinstance(config, dict) or set(config) - {'self', 'other', 'explicitly_requested'}:
        raise ValueError('display_names 僅接受雙方角色名稱及明確指定標記')
    for role in names:
        if role in config:
            label = config[role]
            if not isinstance(label, str) or not label.strip() or len(label) > 40 or any(ord(c) < 32 for c in label):
                raise ValueError('角色名稱須為簡短且非空白的文字')
            names[role] = label.strip()
    if names != DEFAULT_NAMES and config.get('explicitly_requested') is not True:
        raise ValueError('只有使用者明確指定時才可替換你／他，不自動使用匯出名稱')
    if names['self'] == names['other']:
        raise ValueError('雙方角色名稱不可相同')
    return names


def edit_groups(data):
    """Only group source-verified versions; retain every raw record and anchor."""
    records = data['records']
    by_id = {record['id']: record for record in records}
    order = {record['id']: index for index, record in enumerate(records)}
    groups = data.get('edit_groups', [])
    if not isinstance(groups, list):
        raise ValueError('edit_groups 須為已核對來源的編輯群組清單')
    originals, membership = {}, {}
    for group in groups:
        if not isinstance(group, dict) or group.get('source_verified') is not True or not isinstance(group.get('source'), str) or not group['source'].strip():
            raise ValueError('編輯合併需明確的版本來源與 source_verified: true，不從相似文字猜測')
        original, versions = group.get('original_record_id'), group.get('version_record_ids')
        if not isinstance(original, str) or not isinstance(versions, list) or len(versions) < 2 or versions[0] != original:
            raise ValueError('編輯群組須由原始訊息開始，並依順序包含至少兩個版本')
        if any(not isinstance(identity, str) or identity not in by_id or identity in membership for identity in versions) or len(versions) != len(set(versions)):
            raise ValueError('編輯版本 ID 不存在、重複或已歸屬其他群組')
        if [order[identity] for identity in versions] != sorted(order[identity] for identity in versions):
            raise ValueError('編輯版本順序須與來源核對後的紀錄順序一致，不能倒置時間線')
        role = by_id[original]['speaker_role']
        if role == 'system' or any(by_id[identity]['speaker_role'] != role for identity in versions):
            raise ValueError('只能合併已確認屬於同一發言者的訊息編輯版本')
        originals[original] = versions
        membership.update((identity, original) for identity in versions)
    return originals, membership


def validate_archive(data):
    validate_reading(data.get('reading_audit'))
    display_names(data)
    expected = {}
    for source in data['reading_audit']['sources']:
        if source.get('source_kind') not in ('message', 'supplement'):
            raise ValueError('對話回顧需標示每個閱讀來源為 message 或 supplement')
        if source['source_kind'] == 'message':
            expected[source['source_id']] = source['record_count']
    records, segments = data.get('records'), data.get('segments')
    if not isinstance(records, list) or not records or not isinstance(segments, list) or not segments:
        raise ValueError('缺少全部訊息或片段清單')
    ids, record_ids, positions = [], set(), {source: set() for source in expected}
    for record in records:
        identity = record.get('id')
        if not valid_id(identity) or identity in record_ids:
            raise ValueError('訊息 ID 不合法或重複')
        ids.append(identity)
        record_ids.add(identity)
        source, position = record.get('source_id'), record.get('position')
        if source not in expected or type(position) is not int or not 1 <= position <= expected[source] or position in positions[source]:
            raise ValueError('訊息來源／位置不符，或重複收錄原始紀錄')
        positions[source].add(position)
        for key in ('timestamp', 'sender', 'text', 'kind', 'source'):
            if not isinstance(record.get(key), str):
                raise ValueError('訊息缺少時間、說話者、原文、種類或來源')
        if not isinstance(record.get('attachments', []), list) or any(not isinstance(x, str) for x in record.get('attachments', [])):
            raise ValueError('附件欄須為文字清單')
        visible_body(record)
        if record.get('speaker_role') not in ('self', 'other', 'system'):
            raise ValueError('每筆 speaker_role 須依已確認的發言者填寫，不從名字猜測')
        reactions = record.get('reactions', [])
        if not isinstance(reactions, list) or any(not isinstance(r, dict) for r in reactions):
            raise ValueError('reactions 須為已正規化的回應清單')
        for reaction in reactions:
            emoji(reaction.get('emoji'))
        media = record.get('media_types', [])
        if not isinstance(media, list) or any(x not in ('image', 'video', 'audio', 'file', 'sticker') for x in media):
            raise ValueError('media_types 須為標準附件種類')
    for record in records:
        reply = record.get('reply')
        if reply is not None:
            if not isinstance(reply, dict) or reply.get('source_verified') is not True:
                raise ValueError('reply 只能根據來源明確的引用欄位設定，需 source_verified: true')
            target = reply.get('record_id')
            if target is not None and (target not in record_ids or target == record['id']):
                raise ValueError('引用目標須為已核對的原始訊息，不可自我引用或猜測不存在 ID')
            if target is None and not isinstance(reply.get('text', ''), str):
                raise ValueError('找不到原訊息時，只能顯示來源中確實提供的引用文字')
        if not isinstance(record.get('media', []), list):
            raise ValueError('media 須為附件清單')
        if 'share_url' in record and not isinstance(record['share_url'], str):
            raise ValueError('share_url 須為匯出中的原始網址')
    if any(len(positions[key]) != count for key, count in expected.items()):
        raise ValueError('對話回顧漏掉原始訊息紀錄')
    segment_ids, flattened = [], []
    for segment in segments:
        identity = segment.get('id')
        if not valid_id(identity) or identity in record_ids or identity in segment_ids:
            raise ValueError('片段 ID 不合法或與其他 ID 重複')
        segment_ids.append(identity)
        record_ids.add(identity)
        cats, members = segment.get('categories'), segment.get('record_ids')
        if not isinstance(cats, list) or not cats or any(c not in CATEGORIES for c in cats) or len(cats) != len(set(cats)):
            raise ValueError('片段須有五類中的至少一種氣氛，不可重複標籤')
        if not isinstance(members, list) or not members:
            raise ValueError('片段沒有訊息紀錄')
        for key in ('title', 'date'):
            if not isinstance(segment.get(key), str):
                raise ValueError('片段缺少標題或日期')
        flattened.extend(members)
    if flattened != ids:
        raise ValueError('片段須按原始排列連續完整涵蓋訊息，不得漏筆、重複或任意重排')
    edit_groups(data)
    return set(segment_ids)


def context_anchor(identity):
    if not valid_id(identity):
        raise ValueError("片段 ID 不合法")
    return "chat-segment-" + identity


def render(data, materials_root=None):
    validate_archive(data)
    names = display_names(data)
    by_id = {r['id']: r for r in data['records']}
    groups, membership = edit_groups(data)
    materials = Materials(materials_root)
    original_segments = {identity: segment['id'] for segment in data['segments'] for identity in segment['record_ids'] if identity in groups}

    def content(r):
        """Render a single snapshot, including media and exact-version replies."""
        kind = display_type(r)
        material_items = r.get('media', [])
        represented = {m.get('type') for m in material_items if isinstance(m, dict)}
        media_types = r.get('media_types', [])
        if not media_types and r.get('attachments') and kind == 'text' and not material_items:
            media_types = ['file']
        media_text = ''.join(MARKERS[m] for m in media_types if m != kind and m not in represented)
        attachment_html = ''.join(materials.render(item) for item in material_items)
        if kind in ('reel', 'threads_post'):
            body_html = link(r.get('share_url'), MARKERS[kind], platform=kind, attachment=True)
            if r.get('share_url') and body_html == esc(MARKERS[kind]):
                body_html += '（這個連結無法安全顯示）'
            elif not r.get('share_url'):
                body_html += '（匯出檔沒有附連結）'
            if r.get('comment'):
                body_html += '\n' + linked_text(r['comment'])
        else:
            body_html = linked_text(visible_body(r))
        quote = ''
        reply = r.get('reply')
        if reply:
            if reply.get('record_id'):
                original = by_id[reply['record_id']]
                who = '系統通知' if original['speaker_role'] == 'system' else names[original['speaker_role']]
                preview = visible_body(original)
                if len(preview) > 240:
                    preview = preview[:240] + '…（點開看原訊息）'
                quote = f'<blockquote class="reply"><a href="#chat-record-{attr(original["id"])}">回覆 {esc(who)} · {esc(original["timestamp"])}</a><p>{esc(preview)}</p></blockquote>'
            else:
                quote = '<blockquote class="reply"><span>引用的訊息（找不到原訊息）</span><p>' + esc(reply.get('text') or '匯出檔沒有附上引用內容') + '</p></blockquote>'
        reactions = [] if kind == 'reaction' else list(dict.fromkeys(reaction['emoji'] for reaction in r.get('reactions', [])))
        chips = ''.join(f'<span class="reaction">({esc(value)})</span>' for value in reactions)
        return quote + f'<p class="text">{body_html}</p>' + attachment_html + (f'<p class="media">{esc(media_text)}</p>' if media_text else '') + chips

    buttons = '<button type="button" data-filter="">全部</button>' + ''.join(f'<button type="button" data-filter="{esc(c)}">{esc(c)}</button>' for c in CATEGORIES)
    panels = []
    for index, segment in enumerate(data['segments']):
        messages = []
        previous_day = None
        relocated = set()
        for identity in segment['record_ids']:
            r = by_id[identity]
            original_id = membership.get(identity)
            if original_id is not None and identity != original_id:
                if original_segments[original_id] != segment['id'] and original_id not in relocated:
                    messages.append(f'<p class="edit-location"><a href="#chat-edits-{attr(original_id)}">這則修改已經併進原訊息的編輯紀錄，點這裡看</a></p>')
                    relocated.add(original_id)
                continue
            date = re.match(r'^(\d{4}[/-]\d{1,2}[/-]\d{1,2})', r['timestamp'])
            day = date.group(1) if date else segment['date']
            if day != previous_day:
                messages.append(f'<p class="chat-day">{esc(day)}</p>')
                previous_day = day
            time = re.search(r'\b\d{1,2}:\d{2}(?::\d{2})?\b', r['timestamp'])
            time_label = time.group() if time else r['timestamp']
            kind = display_type(r)
            role = r['speaker_role']
            meta = time_label if role == 'system' else names[role] + ' · ' + time_label
            if identity in groups:
                versions = groups[identity]
                latest = by_id[versions[-1]]
                old = []
                for number, version_id in enumerate(versions[:-1]):
                    version = by_id[version_id]
                    label = '原始版本' if number == 0 else f'較早版本 {number + 1}'
                    old.append(f'<div class="edit-version" id="chat-record-{attr(version_id)}"><p class="meta">{esc(label)} · 來源時間 {esc(version["timestamp"])}</p>{content(version)}</div>')
                history = f'<details class="edit-history" id="chat-edits-{attr(identity)}"><summary>編輯紀錄（{len(old)} 個舊版本）</summary><p class="source">時間和位置以第一次傳送為準；上面是最新內容，下面依序是改之前的版本。</p>{"".join(old)}</details>'
                messages.append(f'<div class="message speaker-{role}" id="chat-message-{attr(identity)}"><div class="bubble"><p class="meta">{esc(meta)}</p><div class="latest-version" id="chat-record-{attr(latest["id"])}">{content(latest)}</div><span class="edited">(已編輯)</span>{history}</div></div>')
            else:
                edited = '<span class="edited">(已編輯；匯出檔沒有舊版本)</span>' if r.get('version_status') == 'edited' else ''
                messages.append(f'<div class="message speaker-{role}" id="chat-record-{attr(identity)}"><div class="bubble"><p class="meta">{esc(meta)}</p>{content(r)}{edited}</div></div>')
        navigation = []
        if index:
            navigation.append(f'<a href="#{esc(context_anchor(data["segments"][index-1]["id"]))}">← 上一段</a>')
        if index + 1 < len(data['segments']):
            navigation.append(f'<a href="#{esc(context_anchor(data["segments"][index+1]["id"]))}">下一段 →</a>')
        cats = ' · '.join(segment['categories'])
        panels.append(f'<details class="segment" id="{esc(context_anchor(segment["id"]))}" data-categories="{esc(json.dumps(segment["categories"],ensure_ascii=False))}"><summary>{esc(segment["date"])}｜{esc(segment["title"])}<small>{esc(cats)}</small></summary><p>{esc(segment.get("note", ""))}</p>{"".join(messages)}<nav>{"　".join(navigation)}</nav></details>')
    return f'''<details class="panel conversation-review" id="conversation-review"><summary>完整對話：依氣氛分類</summary>
<a href="#analysis-top">回到關係分析</a><p>這裡收錄你選的這段對話的所有紀錄。文字裡的 email 和手機號碼已經部分遮住，圖片、語音等附件和分享連結保持原樣，所以還是有私密內容。依氣氛分類只是方便你回顧，不代表你們當時的感受一定是這樣。</p><p>共 {len(data['records'])} 筆紀錄，分成 {len(data['segments'])} 段。紀錄數包含貼圖、系統通知等，不等於兩個人說了幾句話。{' 已確認的編輯版本合併顯示，原始紀錄未刪減。' if groups else ''}</p><div aria-label="氣氛篩選">{buttons}</div><label>搜尋片段：<input id="chat-search" type="search" placeholder="輸入想找的文字"></label><p id="chat-count" aria-live="polite"></p><noscript>現在沒辦法篩選，但還是可以照日期點開每一段。</noscript>{''.join(panels)}</details>'''


ARCHIVE_STYLE = '''
.conversation-review .reply{margin:8px 0;padding:8px 12px;border-left:3px solid #8aafa0;background:#ffffff99;font-size:14px;max-height:240px;overflow:auto}
.conversation-review .attachment{margin:8px 0}
.conversation-review .attachment img,.conversation-review video{display:block;max-width:100%;max-height:480px;object-fit:contain;border-radius:8px}
.conversation-review audio{max-width:100%}
.conversation-review figcaption{font-size:13px;color:#526962}
.conversation-review .message{display:flex;padding:5px 0}
.conversation-review .speaker-self{justify-content:flex-end}
.conversation-review .speaker-system{justify-content:center}
.conversation-review .bubble{max-width:85%;padding:12px 16px;border-radius:16px;background:#eef2f0;min-width:100px}
.conversation-review .speaker-self .bubble{background:#e0f0e9}
.conversation-review .speaker-system .bubble{background:transparent;font-size:14px;color:#526962}
.conversation-review .bubble p{margin:3px 0}
.conversation-review .chat-day{text-align:center;font-size:14px;color:#526962;margin:20px 0 10px}
.conversation-review .reaction{display:inline-block;font-size:16px;margin:4px 6px 0 0}
.conversation-review .edited{display:block;font-size:12px;color:#526962}
.conversation-review .edit-history{margin-top:8px;padding:8px 0 0;border-top:1px solid #b8cec3}
.conversation-review .edit-history>summary{font-size:14px;color:#526962;font-weight:500}
.conversation-review .edit-version{background:#ffffff99;border-left:3px solid #aac5b8;margin-top:10px;padding:8px 12px;border-radius:6px}
.conversation-review .edit-location{font-size:14px;color:#526962;margin:10px 0}
.conversation-review .meta,.conversation-review small{display:block;color:#526962;font-size:14px}
.conversation-review button,.conversation-review input{font:inherit;max-width:100%;padding:10px;border:1px solid #a6bfb4;border-radius:8px;margin:5px}
.conversation-review button{cursor:pointer;background:white}
.conversation-review button.active{background:#226a60;color:white}
.conversation-review [hidden]{display:none!important}
.conversation-review>summary{font-size:24px}
'''

ARCHIVE_SCRIPT = '''(()=>{
const root=document.getElementById('conversation-review');if(!root)return;
const segments=[...root.querySelectorAll('.segment')],buttons=[...root.querySelectorAll('[data-filter]')],search=document.getElementById('chat-search');let filter='';
function apply(){let n=0;const q=search.value.trim().toLocaleLowerCase();for(const s of segments){s.hidden=!!((filter&&!JSON.parse(s.dataset.categories).includes(filter))||(q&&!s.textContent.toLocaleLowerCase().includes(q)));if(!s.hidden)n++;}for(const b of buttons){b.classList.toggle('active',b.dataset.filter===filter);b.setAttribute('aria-pressed',String(b.dataset.filter===filter));}document.getElementById('chat-count').textContent='顯示 '+n+'／'+segments.length+' 段';}
for(const b of buttons)b.addEventListener('click',()=>{filter=b.dataset.filter;apply();});search.addEventListener('input',apply);
function reveal(requestedId){let id;try{id=typeof requestedId==='string'?requestedId:decodeURIComponent(location.hash.slice(1));}catch{return}const target=document.getElementById(id);if(!target||!root.contains(target))return;filter='';search.value='';apply();let node=target;while(node&&node!==root.parentElement){if(node.tagName==='DETAILS')node.open=true;node=node.parentElement;}requestAnimationFrame(()=>target.scrollIntoView());}
document.addEventListener('click',event=>{const link=event.target.closest('a[href^="#"]');if(!link)return;const href=link.getAttribute('href');let id;try{id=decodeURIComponent(href.slice(1));}catch{return}const target=document.getElementById(id);if(target&&root.contains(target)){event.preventDefault();if(location.hash!==href)location.hash=href;reveal(id);}});
window.addEventListener('hashchange',reveal);apply();reveal();
})();'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding='utf-8'))
    validate_archive(data)
    print('完整對話清單驗證通過；請用 render_html.py --archive 一次產出整合 HTML。')


if __name__ == '__main__':
    main()
