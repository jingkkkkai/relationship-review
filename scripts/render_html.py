#!/usr/bin/env python3
"""Render verified relationship report JSON as a standalone escaped HTML."""
import html
import argparse
import json
from pathlib import Path
import re
import sys


from presentation import esc, attr, linked_text


def validate_reading(audit):
    """Check declared reading coverage, not whether a model understood it."""
    if not isinstance(audit, dict) or not isinstance(audit.get('sources'), list) or not audit['sources']:
        raise ValueError('缺少 reading_audit：全部訊息閱讀完成並核對清單後，才可產出報告')
    seen, total = set(), 0
    for source in audit['sources']:
        if not isinstance(source, dict):
            raise ValueError('閱讀來源格式錯誤')
        identity, count = source.get('source_id'), source.get('record_count')
        if not isinstance(identity, str) or not identity.strip() or identity in seen:
            raise ValueError('閱讀來源 ID 缺失或重複')
        seen.add(identity)
        if type(count) is not int or count < 0:
            raise ValueError('來源紀錄數必須是非負整數')
        ranges = source.get('reviewed_ranges')
        if not isinstance(ranges, list):
            raise ValueError('缺少實際已讀區段')
        ordered = []
        for item in ranges:
            if not isinstance(item, dict):
                raise ValueError('已讀區段格式錯誤')
            start, end = item.get('start'), item.get('end')
            if type(start) is not int or type(end) is not int or start < 1 or end < start or end > count:
                raise ValueError('已讀區段位置超出原始來源範圍')
            if item.get('status') != 'read' or not isinstance(item.get('note'), str) or not item['note'].strip():
                raise ValueError('仍有未完成閱讀區段，或缺少實際閱讀筆記')
            ordered.append((start, end))
        next_position = 1
        for start, end in sorted(ordered):
            if start != next_position:
                raise ValueError('閱讀區段有缺口或重複；請先核對並完成全部閱讀')
            next_position = end + 1
        if next_position != count + 1:
            raise ValueError('訊息尚未全部閱讀，不產出分析報告')
        total += count
    if not total:
        raise ValueError('沒有可分析的文字紀錄')
    attachments = audit.get('attachments')
    if not isinstance(attachments, list):
        raise ValueError('缺少附件處理清單；沒有附件時請提供空清單')
    seen_attachments = set()
    for item in attachments:
        if not isinstance(item, dict):
            raise ValueError('附件清單格式錯誤')
        identity = item.get('id')
        if not isinstance(identity, str) or not identity.strip() or identity in seen_attachments:
            raise ValueError('附件 ID 缺失或重複')
        seen_attachments.add(identity)
        if item.get('kind') not in ('image', 'audio', 'video', 'other'):
            raise ValueError('附件種類不明')
        if item.get('status') not in ('read', 'unavailable'):
            raise ValueError('仍有待處理附件；先閱讀或如實說明不可讀原因')
        if not isinstance(item.get('reason'), str) or not item['reason'].strip():
            raise ValueError('缺少附件處理說明')


def render(data, archive=None, materials_root=None):
    validate_reading(data.get('reading_audit'))
    from render_archive import validate_archive, render as render_conversations, context_anchor, display_names, pronoun_note, ARCHIVE_STYLE, ARCHIVE_SCRIPT
    names = display_names(data)
    index = data.get('conversation_index')
    archive_body, archive_style, archive_script = '', '', ''
    valid_contexts = set()
    if index is not None:
        if archive is None:
            raise ValueError('完整脈絡需實際 archive.json；CLI 請加 --archive')
        valid_contexts = validate_archive(archive)
        if index.get('section_id') != 'conversation-review' or 'file' in index:
            raise ValueError('請使用 section_id: conversation-review 的頁內索引，不再輸出第二份 HTML')
        declared = index.get('segment_ids')
        if not isinstance(declared, list) or len(declared) != len(set(declared)) or set(declared) != valid_contexts:
            raise ValueError('對話索引與完整回顧的片段不一致')
        if archive.get('reading_audit') != data['reading_audit']:
            raise ValueError('分析與完整回顧使用的閱讀清單不一致')
        if display_names(archive) != names:
            raise ValueError('分析與對話回顧的角色名稱不一致')
        archive_body = render_conversations(archive, materials_root=materials_root)
        archive_style, archive_script = ARCHIVE_STYLE, ARCHIVE_SCRIPT
    elif archive is not None:
        raise ValueError('缺少完整對話的頁內索引')
    events, evidence = data['events'], data['evidence']
    ids = [item['id'] for item in events + evidence]
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r'[A-Za-z0-9_-]+', i) for i in ids):
        raise ValueError('ID 必須唯一且僅含英數字、底線或連字號')
    reserved_ids = {'analysis-top', 'conversation-review', 'chat-search', 'chat-count', 'event-picker', 'relationship-summary', 'relationship-changes', 'event-review', 'repair-summary', 'mobile-return', 'mobile-return-style', 'mobile-return-script', 'return-section', 'return-top'}
    if archive is not None:
        reserved_ids.update(context_anchor(s['id']) for s in archive['segments'])
        reserved_ids.update('chat-record-' + r['id'] for r in archive['records'])
        reserved_ids.update('chat-message-' + r['id'] for r in archive['records'])
        reserved_ids.update('chat-edits-' + r['id'] for r in archive['records'])
    if set(ids) & reserved_ids:
        raise ValueError('分析 ID 與頁面導覽或對話 ID 衝突，請更換分析 ID')
    known = {item['id'] for item in evidence}
    evidence_by_id = {item['id']: item for item in evidence}

    def section(item):
        references = item.get('evidence_ids', [])
        if any(ref not in known for ref in references):
            raise ValueError('有不存在的證據 ID')
        links = ' '.join(f'<a class="ref" href="#{esc(ref)}">{esc(ref)}</a>' for ref in references)
        return f'<details><summary>{esc(item["title"])}</summary><p>{linked_text(item["text"])}</p><div>{links}</div></details>'

    def state_item(item):
        if not isinstance(item, dict) or not isinstance(item.get('text'), str) or not item['text'].strip() or not isinstance(item.get('evidence_ids'), list):
            raise ValueError('階段狀態、變化與限制須有 text 及 evidence_ids；不足時明說')
        if any(not isinstance(ref, str) or ref not in known for ref in item['evidence_ids']):
            raise ValueError('階段狀態包含不存在的證據 ID')
        return item

    def stage_states(stage, previous):
        states = stage.get('states')
        if not isinstance(states, dict) or set(states) != {'self', 'other'}:
            raise ValueError('每個階段須分別提供 states.self 與 states.other，不省略任何一方')
        people = []
        for role in ('self', 'other'):
            state = states[role]
            if not isinstance(state, dict):
                raise ValueError('每方狀態須包含 current、change、exceptions')
            current = state_item(state.get('current'))
            change = state_item(state.get('change'))
            exceptions = state_item(state.get('exceptions'))
            status = change.get('status')
            if previous is None:
                if status != 'baseline':
                    raise ValueError('第一階段為 baseline，沒有前階段，不可補造變化')
            elif status not in ('compared', 'insufficient'):
                raise ValueError('後續階段須標 compared 或 insufficient，不把資料缺口當變化')
            if status == 'compared':
                message_contexts = {context for ref in change['evidence_ids'] if evidence_by_id[ref].get('type') in ('訊息紀錄', '訊息中的主張') for context in evidence_by_id[ref].get('context_segment_ids', [])}
                if not message_contexts.intersection(previous['segment_ids']) or not message_contexts.intersection(stage['segment_ids']):
                    raise ValueError('狀態比較須同時連到前一階段與本階段的訊息依據；僅有單側或補述時使用 insufficient')
            references = ' '.join(f'<a class="ref" href="#{attr(ref)}">{esc(ref)}</a>' for ref in current['evidence_ids'])
            heading = '和前一階段相比' if previous is not None else '起始觀察'
            change_body = section(dict(change, title=heading))
            exceptions_body = section(dict(exceptions, title='例外、修復和還不確定的地方'))
            people.append(f'<div class="stage-person"><h4>{esc(names[role])}這時的狀態</h4><p>{linked_text(current["text"])}</p><div>{references}</div>{change_body}{exceptions_body}</div>')
        context = state_item(stage.get('state_context'))
        return '<div class="stage-states">' + ''.join(people) + '</div>' + section(dict(context, title='可能的原因'))

    concepts = data.get('concepts')
    if not isinstance(concepts, dict) or set(concepts) != {'self', 'other', 'shared'}:
        raise ValueError('心理學概念須分為 self、other、shared 三部分，不適用時明說原因')
    concept_groups = []
    for key, label in (('self', '關於' + names['self']), ('other', '關於' + names['other']), ('shared', '關於你們的互動')):
        group = concepts[key]
        if not isinstance(group, dict) or not isinstance(group.get('items'), list):
            raise ValueError('每組概念須有 items 清單')
        summary = group.get('summary', '')
        if not isinstance(summary, str) or not group['items'] and not summary.strip():
            raise ValueError('沒有適用概念時須提供白話說明，不可為湊欄位硬套')
        concept_groups.append(f'<div class="concept-group"><h3>{esc(label)}</h3><p>{linked_text(summary)}</p>{"".join(section(item) for item in group["items"])}</div>')
    concept_body = ''.join(concept_groups)

    from mobile_navigation import HEAD as mobile_head, BODY as mobile_body

    title = esc(data.get('title', '關係回顧'))
    bullets = ''.join(f'<li>{esc(t)}</li>' for t in data['takeaways'])
    stages = data.get('stage_review')
    if not isinstance(stages, list) or not stages:
        raise ValueError('需提供 stage_review，依互動轉折分階段呈現雙方需求與調整，不再逐月切分')
    stage_cards, phase_cards, assigned = [], [], []
    fields = (('self_needs', names['self'] + '的需要'), ('other_needs', names['other'] + '的需要'), ('self_improvements', names['self'] + '可以怎麼調整'), ('other_improvements', names['other'] + '可以怎麼調整'))
    for stage_index, stage in enumerate(stages):
        if not isinstance(stage, dict) or any(not isinstance(stage.get(key), str) or not stage[key].strip() for key in ('title', 'period', 'summary')):
            raise ValueError('每個階段須有 title、period、summary；日期不明時如實說明')
        members = stage.get('segment_ids')
        if not isinstance(members, list) or any(not isinstance(c, str) or c not in valid_contexts for c in members) or archive is not None and not members:
            raise ValueError('階段須連到有效且非空的對話片段清單，不能猜測來源')
        assigned.extend(members)
        content = []
        for key, heading in fields:
            item = stage.get(key)
            if not isinstance(item, dict) or not isinstance(item.get('text'), str) or not item['text'].strip():
                raise ValueError('每個階段須分別提供雙方需求與調整方向；未知時明說')
            content.append(section(dict(item, title=heading)))
        links = ' '.join(f'<a class="ref" href="#{attr(context_anchor(c))}">從這個階段的第一段對話開始看</a>' for c in members[:1])
        states_body = stage_states(stage, stages[stage_index - 1] if stage_index else None)
        stage_cards.append(f'<div class="stage-detail"><h3>{esc(stage["title"])}</h3><p class="date">{esc(stage["period"])}</p><p>{esc(stage["summary"])}</p>{states_body}{"".join(content)}<div>{links}</div></div>')
        phase_cards.append(f'<div class="phase"><strong>{esc(stage["title"])}</strong><p>{esc(stage["period"])}</p></div>')
    if archive is not None and assigned != [segment['id'] for segment in archive['segments']]:
        raise ValueError('階段須依原始片段順序完整涵蓋，不得漏段、重複或任意重排；可跨月或同月分段')
    stage_body, overview = ''.join(stage_cards), ''.join(phase_cards)

    def event_interaction(event):
        # Older report JSON can reuse its role groups without repeating the old UI notice.
        groups = event.get('interaction', event.get('psychology'))
        if 'interaction' in event and 'psychology' in event and event['interaction'] != event['psychology']:
            raise ValueError('事件的 interaction 與舊 psychology 內容不同，請保留核對後的一份')
        if not isinstance(groups, dict) or set(groups) != {'self', 'other'}:
            raise ValueError('每個事件須有 interaction.self 與 interaction.other，呈現當次反應及影響')
        parts = []
        for role in ('self', 'other'):
            group = groups[role]
            if not isinstance(group, dict) or not isinstance(group.get('summary'), str) or not isinstance(group.get('items'), list) or (not group['summary'].strip() and not group['items']):
                raise ValueError('每方事件反應須有 summary 與 items；缺少可觀察內容時說明具體缺口')
            for item in group['items']:
                if not isinstance(item, dict) or not isinstance(item.get('evidence_ids'), list) or not item['evidence_ids']:
                    raise ValueError('每項事件反應須有可回查的訊息或補述依據')
                if any(not isinstance(item.get(key), str) or not item[key].strip() for key in ('title', 'text')):
                    raise ValueError('事件反應需說明具體回應及影響，不能只有標題')
            intro = f'<p>{linked_text(group["summary"])}</p>' if group['summary'].strip() else ''
            parts.append(f'<div class="event-interaction-group"><h4>{esc(names[role])}的反應</h4>{intro}{"".join(section(item) for item in group["items"])}</div>')
        return '<details class="event-interaction"><summary>這次雙方怎麼回應</summary>' + ''.join(parts) + '</details>'

    from repair_review import render as render_repairs
    repair_summary, event_repairs, repair_style = render_repairs(data.get('repair_review'), events, archive, known, names)

    options = ''.join(f'<option value="{esc(e["id"])}">{esc(e["date"])} · {esc(e["title"])}</option>' for e in events)
    timeline = ''.join(f'<li><a href="#{esc(e["id"])}">{esc(e["date"])} · {esc(e["title"])}</a></li>' for e in events)
    cards = ''.join(f'<article id="{esc(e["id"])}"><div class="date">{esc(e["date"])}</div><h3>{esc(e["title"])}</h3><p>{esc(e["summary"])}</p>{"".join(section(s) for s in e["sections"])}{event_interaction(e)}{event_repairs.get(e['id'], '')}</article>' for e in events)
    overall = ''.join(section(s) for s in data['overall'])
    proofs = []
    message_types = ('訊息紀錄', '訊息中的主張')
    for e in evidence:
        contexts = e.get('context_segment_ids', [])
        if not isinstance(contexts, list) or any(c not in valid_contexts for c in contexts):
            raise ValueError('引用含不存在的完整脈絡片段')
        if e['type'] in message_types and not contexts:
            raise ValueError('訊息依據不能只有短摘錄，請連到完整對話片段')
        links = ' '.join(f'<a class="ref" href="#{esc(context_anchor(c))}">看完整對話脈絡 · {esc(c)}</a>' for c in contexts)
        source_label = '聊天紀錄' if e['type'] in message_types else '補充敘述' if e['type'] in ('事後回憶', '當時筆記', '當事人補述') else e['type']
        proofs.append(f'<details id="{esc(e["id"])}"><summary>{esc(e["id"])} · {esc(e["type"])}</summary><p>{esc(e["text"])}</p><p class="source">來源：{esc(source_label)}</p>{links}</details>')
    proof = ''.join(proofs)
    archive_link = '<p><a href="#conversation-review">按日期與氣氛回顧全部對話</a></p>' if archive_body else ''
    return f'''<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; media-src data:; base-uri 'none'; form-action 'none'">
<title>{title}</title><style>
:root{{color-scheme:light;--ink:#243c40;--green:#226a60;--line:#d7e4de}}*{{box-sizing:border-box}}body{{margin:0;background:#f6f5ef;color:var(--ink);font:18px/1.8 system-ui,-apple-system,'PingFang TC','Microsoft JhengHei',sans-serif}}main{{max-width:1000px;margin:auto;padding:32px 24px}}h1{{font-size:clamp(32px,5vw,52px);line-height:1.25}}h2{{line-height:1.4}}p{{white-space:pre-wrap;overflow-wrap:anywhere}}a{{color:var(--green);overflow-wrap:anywhere}}header,article,.panel{{background:white;padding:26px;border:1px solid var(--line);border-radius:18px;margin:24px 0}}.scope,.source,.date{{font-size:15px;color:#536862}}.coverage{{background:#eef4f0;padding:16px;border-radius:12px}}.stage-detail{{margin-top:24px;border-top:1px solid var(--line);padding-top:16px}}.phases{{display:flex;gap:12px;flex-wrap:wrap}}.phase{{flex:1 1 180px;background:#e9f3ed;padding:18px;border-radius:14px}}.phase strong{{font-size:24px}}details{{border-top:1px solid var(--line);padding:12px 0}}summary{{cursor:pointer;font-weight:650}}select{{max-width:100%;padding:12px;font:inherit;border:1px solid var(--line);border-radius:10px}}.ref{{display:inline-block;background:#edf3f0;border-radius:6px;padding:2px 8px;margin:3px;font-size:14px}}article,details{{scroll-margin-top:20px}}:target{{outline:3px solid #77a99c;outline-offset:5px}}@media(max-width:600px){{main{{padding:16px 12px}}header,article,.panel{{padding:18px}}body{{font-size:17px}}}}@media print{{body{{background:white}}select{{display:none}}article{{break-inside:avoid}}}}
{archive_style}
{repair_style}
.stage-states{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:18px 0}}
.stage-person{{background:#f0f5f1;padding:18px;border-radius:12px;min-width:0}}
.stage-person h4{{font-size:19px;margin:0 0 10px}}
.pronoun-note{{background:#eaf3ee;border-radius:12px;padding:10px 14px;font-size:16px}}
@media(max-width:640px){{.stage-states{{grid-template-columns:1fr}}}}
</style>{mobile_head}</head><body><main>
<header id="analysis-top"><p>讀懂互動，整理下一步</p><h1>{title}</h1><p class="pronoun-note">{esc(pronoun_note(names))}</p><h2>注意事項</h2><aside class="coverage" aria-label="資料使用限制"><strong>你提供的對話和這份報告，只用在這次的關係回顧</strong><p>訊息、圖片、附件、補充說明和分析內容，只拿來製作、檢查和修改這份報告；不會拿去做別的事，也不會公開、轉給別人，或當成研究、訓練、測試、宣傳和示範的素材。</p><p>這個工具不會把對話或分析另外存進任何記憶功能。不過整理過程中還是會用到對話內容和進度檔；你用的平台會不會自動保存、記住或拿去訓練，要看平台自己的設定，這個工具沒辦法保證。</p><p>文字裡的 email 和手機號碼已經部分遮住；圖片、語音等附件和分享連結保持原樣，沒有遮。遮住文字不等於完全匿名，檔案裡還是有私密內容，請好好保管。</p></aside><p class="scope">資料來源與範圍：{esc(data['scope'])}</p><p class="coverage">讀了哪些、缺了哪些：{esc(data['coverage'])}</p><p class="source">這份回顧只根據你提供的紀錄和補充整理，寫下看得到的互動和可能的解讀；沒有寫在訊息裡的事，這裡看不到。這不是心理診斷，不會因為一次互動就斷定一個人是怎樣的人，也不會替你們決定要不要繼續。</p></header>
<section class="panel" id="relationship-summary"><h2>關係總結</h2><ul>{bullets}</ul>{repair_summary}{overall}<h3>心理學參考</h3>{concept_body}</section>
<section class="panel" id="relationship-changes"><h2>關係如何變化</h2><p class="source">每個階段把兩個人的狀態、需要和可以調整的地方放在一起看；點開可以看到前後變化、例外和可能的原因，也能連回原文。</p><div class="phases">{overview}</div>{stage_body}</section>
<section id="event-review"><h2>事件回顧</h2><nav class="panel" aria-label="事件導航"><h3>選個事件</h3><label for="event-picker">事件：</label><select id="event-picker"><option value="">請選擇</option>{options}</select><ol>{timeline}</ol></nav>{cards}<details class="panel"><summary>分析依據</summary><p class="source">訊息只能證明這句話有人說過，不代表內容一定是真的。事後回憶、推測和還不知道的事，請分開看。</p>{proof}</details></section>
{archive_body}</main><script>
document.getElementById('event-picker').addEventListener('change',function(){{if(this.value)location.hash=this.value;}});
function reveal(requestedId){{var id;try{{id=typeof requestedId==='string'?requestedId:decodeURIComponent(location.hash.slice(1));}}catch{{return;}}var target=document.getElementById(id);for(var node=target;node;node=node.parentElement){{if(node.tagName==='DETAILS')node.open=true;}}}}
document.addEventListener('click',function(event){{var link=event.target.closest('a[href^="#"]');if(link){{try{{reveal(decodeURIComponent(link.getAttribute('href').slice(1)));}}catch{{}}}}}});
window.addEventListener('hashchange',reveal);reveal();
{archive_script}
</script>{mobile_body}</body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('--archive', required=True)
    parser.add_argument('--materials-root', help='本次附件所在資料夾；附件只能由此處嵌入，不讀取其他位置')
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding='utf-8'))
    output = Path(args.output)
    archive = json.loads(Path(args.archive).read_text(encoding='utf-8')) if args.archive else None
    result = render(data, archive, materials_root=args.materials_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result, encoding='utf-8')
    print(str(output))


if __name__ == '__main__':
    main()
