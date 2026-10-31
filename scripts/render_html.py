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
    from render_archive import validate_archive, render as render_conversations, context_anchor, display_names, ARCHIVE_STYLE, ARCHIVE_SCRIPT
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
    reserved_ids = {'analysis-top', 'conversation-review', 'chat-search', 'chat-count', 'event-picker', 'relationship-summary', 'relationship-changes', 'event-review'}
    if archive is not None:
        reserved_ids.update(context_anchor(s['id']) for s in archive['segments'])
        reserved_ids.update('chat-record-' + r['id'] for r in archive['records'])
    if set(ids) & reserved_ids:
        raise ValueError('分析 ID 與頁面導覽或對話 ID 衝突，請更換分析 ID')
    known = {item['id'] for item in evidence}

    def section(item):
        references = item.get('evidence_ids', [])
        if any(ref not in known for ref in references):
            raise ValueError('有不存在的證據 ID')
        links = ' '.join(f'<a class="ref" href="#{esc(ref)}">{esc(ref)}</a>' for ref in references)
        return f'<details><summary>{esc(item["title"])}</summary><p>{linked_text(item["text"])}</p><div>{links}</div></details>'

    concepts = data.get('concepts')
    if not isinstance(concepts, dict) or set(concepts) != {'self', 'other', 'shared'}:
        raise ValueError('心理學概念須分為 self、other、shared 三部分，不適用時明說原因')
    concept_groups = []
    for key, label in (('self', names['self'] + '可以探索的概念'), ('other', names['other'] + '可以探索的概念'), ('shared', '共同可以探索的概念')):
        group = concepts[key]
        if not isinstance(group, dict) or not isinstance(group.get('items'), list):
            raise ValueError('每組概念須有 items 清單')
        summary = group.get('summary', '')
        if not isinstance(summary, str) or not group['items'] and not summary.strip():
            raise ValueError('沒有適用概念時須提供白話說明，不可為湊欄位硬套')
        concept_groups.append(f'<div class="concept-group"><h3>{esc(label)}</h3><p>{linked_text(summary)}</p>{"".join(section(item) for item in group["items"])}</div>')
    concept_body = ''.join(concept_groups)

    title = esc(data.get('title', '關係回顧'))
    bullets = ''.join(f'<li>{esc(t)}</li>' for t in data['takeaways'])
    stages = data.get('stage_review')
    if not isinstance(stages, list) or not stages:
        raise ValueError('需提供 stage_review，依互動轉折分階段呈現雙方需求與調整，不再逐月切分')
    stage_cards, phase_cards, assigned = [], [], []
    fields = (('self_needs', names['self'] + '在這階段的核心需求'), ('other_needs', names['other'] + '在這階段的核心需求'), ('self_improvements', names['self'] + '在這階段可調整的方向'), ('other_improvements', names['other'] + '在這階段可調整的方向'))
    for stage in stages:
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
        links = ' '.join(f'<a class="ref" href="#{attr(context_anchor(c))}">從這階段的第一段對話開始回顧</a>' for c in members[:1])
        stage_cards.append(f'<div class="stage-detail"><h3>{esc(stage["title"])}</h3><p class="date">{esc(stage["period"])}</p><p>{esc(stage["summary"])}</p>{"".join(content)}<div>{links}</div></div>')
        phase_cards.append(f'<div class="phase"><strong>{esc(stage["title"])}</strong><p>{esc(stage["period"])}</p></div>')
    if archive is not None and assigned != [segment['id'] for segment in archive['segments']]:
        raise ValueError('階段須依原始片段順序完整涵蓋，不得漏段、重複或任意重排；可跨月或同月分段')
    stage_body, overview = ''.join(stage_cards), ''.join(phase_cards)

    def event_psychology(event):
        groups = event.get('psychology')
        if not isinstance(groups, dict) or set(groups) != {'self', 'other'}:
            raise ValueError('每個事件須有 psychology.self 與 psychology.other；無適用概念時明說，不硬套')
        parts = []
        for role in ('self', 'other'):
            group = groups[role]
            if not isinstance(group, dict) or not isinstance(group.get('summary'), str) or not group['summary'].strip() or not isinstance(group.get('items'), list):
                raise ValueError('每方事件心理觀察須有 summary 與 items，保留當次反應的限制')
            for item in group['items']:
                if not isinstance(item, dict) or not isinstance(item.get('evidence_ids'), list) or not item['evidence_ids']:
                    raise ValueError('每項事件心理觀察須有可回查的證據；理論來源不能代替事件證據')
            parts.append(f'<div class="event-psychology-group"><h4>{esc(names[role])}在這次互動的反應</h4><p>{linked_text(group["summary"])}</p>{"".join(section(item) for item in group["items"])}</div>')
        return '<details class="event-psychology"><summary>這次互動的心理學觀察</summary><p class="source">這裡探索當次行為可能的心理歷程，包含做得好的反應；不是人格、動機或診斷的判決。一次表現不代表穩定習慣。</p>' + ''.join(parts) + '</details>'

    options = ''.join(f'<option value="{esc(e["id"])}">{esc(e["date"])} · {esc(e["title"])}</option>' for e in events)
    timeline = ''.join(f'<li><a href="#{esc(e["id"])}">{esc(e["date"])} · {esc(e["title"])}</a></li>' for e in events)
    cards = ''.join(f'<article id="{esc(e["id"])}"><div class="date">{esc(e["date"])}</div><h3>{esc(e["title"])}</h3><p>{esc(e["summary"])}</p>{"".join(section(s) for s in e["sections"])}{event_psychology(e)}</article>' for e in events)
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
{archive_style}</style></head><body><main>
<header id="analysis-top"><p>讀懂互動，整理下一步</p><h1>{title}</h1><h2>注意事項</h2><aside class="coverage" aria-label="資料使用限制"><strong>輸入對話與產出報告，僅供本次關係回顧使用</strong><p>訊息、圖片、附件、補述、報告及衍生分析，只供製作、查核與修訂本次報告，不得挪作其他用途、公開、轉交，或另作研究、訓練、測試、宣傳與示範素材。</p><p>本工具不將對話或分析另存至任何可操作的記憶層。本次處理仍需要對話上下文與工作進度檔；平台自動保存、記憶及訓練設定須另外確認，本工具無法代為保證。</p><p>報告中的電子郵件與手機號碼已部分遮蔽；可辨識個人的圖片及附件須先檢查、遮蔽後才能嵌入。遮蔽不等於完全匿名，原文仍可能含姓名、地址或其他私密線索，請妥善保管整份檔案。</p></aside><p class="scope">資料來源與範圍：{esc(data['scope'])}</p><p class="coverage">閱讀狀況與缺口：{esc(data['coverage'])}</p><p class="source">這份回顧依提供的紀錄與補述整理，呈現可觀察的互動與可能解讀，仍可能缺少線下脈絡。它不是心理診斷，也不替雙方決定關係去留。</p></header>
<section class="panel" id="relationship-summary"><h2>關係總結</h2><ul>{bullets}</ul>{overall}<h3>可以探索的心理學概念</h3>{concept_body}</section>
<section class="panel" id="relationship-changes"><h2>關係如何變化</h2><p class="source">需求與調整以整個階段整合；具體事件與例子可展開依據查看。</p><div class="phases">{overview}</div>{stage_body}</section>
<section id="event-review"><h2>事件回顧</h2><nav class="panel" aria-label="事件導航"><h3>選一個事件看看</h3><label for="event-picker">事件：</label><select id="event-picker"><option value="">請選擇</option>{options}</select><ol>{timeline}</ol></nav>{cards}<details class="panel"><summary>查核依據與來源</summary><p class="source">訊息證明某句話被說過，不直接證明其主張屬實。回憶、推論與未知應分開閱讀。</p>{proof}</details></section>
{archive_body}</main><script>
document.getElementById('event-picker').addEventListener('change',function(){{if(this.value)location.hash=this.value;}});
function reveal(requestedId){{var id;try{{id=typeof requestedId==='string'?requestedId:decodeURIComponent(location.hash.slice(1));}}catch{{return;}}var target=document.getElementById(id);for(var node=target;node;node=node.parentElement){{if(node.tagName==='DETAILS')node.open=true;}}}}
document.addEventListener('click',function(event){{var link=event.target.closest('a[href^="#"]');if(link){{try{{reveal(decodeURIComponent(link.getAttribute('href').slice(1)));}}catch{{}}}}}});
window.addEventListener('hashchange',reveal);reveal();
{archive_script}
</script></body></html>'''


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
