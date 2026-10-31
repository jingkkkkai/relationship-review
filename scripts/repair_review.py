"""Validate and render human-coded repair observations. No semantic classification."""
from presentation import esc,attr

CATEGORIES={'goodwill':'示好或接住善意','responsibility':'承認自己的部分','adjustment':'讓步或調整','apology':'有道歉'}
STYLES={'direct':'直接道歉','explanation':'也解釋原因','boundary':'守住自己的界線','impact_qualified':'只為部分影響道歉','conditional_exchange':'要另一方先做到才道歉','negating':'說完又收回或推給別人','irony':'聽起來像反話','uncertain':'語氣看不出來'}
STATUS={'clear':'有道歉','limited':'有道歉，範圍或解釋另外說明','irony':'像反話，另外列，不算道歉','uncertain':'還不確定，先不算道歉','none':'這次沒有明說道歉'}
SOURCES={'message':'有訊息可查','supplement':'來自補充說明，沒有其他資料對照','claim':'事後轉述','unsent':'沒送出的草稿'}
INITIATIVES={'initiated':'主動開口','responded':'回應另一方','uncertain':'看不出是主動還是回應'}
STYLE='''
.repair-summary{margin:24px 0;padding:18px;background:#f0f5ef;border:1px solid #d4e2d7;border-radius:14px}.repair-scroll{overflow-x:auto}.repair-summary table{width:100%;border-collapse:collapse;min-width:420px;font-size:15px}.repair-summary th,.repair-summary td{border-bottom:1px solid #d4e2d7;padding:10px;text-align:left;vertical-align:top}.repair-summary th{background:#e1ece1}.repair-note{font-size:14px;color:#52675c}.repair-event{margin-top:18px}.repair-entry{padding:12px 0}.repair-entry p{font-size:15px}.repair-tags{color:#376249}.repair-links{display:flex;flex-wrap:wrap;gap:8px}.repair-links a{font-size:13px}.repair-order{font-size:14px;color:#52675c}
'''

def validate(review,events,archive,known):
 if not isinstance(review,dict) or any(not isinstance(review.get(k),str) or not review[k].strip() for k in ('method','scope')):raise ValueError('修復表須說明本次範圍與計數口徑')
 event_ids={e['id'] for e in events};by_id={r['id']:r for r in archive['records']}
 coverage=review.get('events');entries=review.get('entries')
 if not isinstance(coverage,list) or {e.get('event_id') for e in coverage}!=event_ids or len(coverage)!=len(event_ids):raise ValueError('修復表須逐事件標明狀態，不遺漏或重複事件')
 for event in coverage:
  if set(event.get('status',{}))!={'self','other'} or any(s not in {'confirmed','not_confirmed','not_applicable'} for s in event['status'].values()):raise ValueError('雙方修復狀態須明說；未確認不是零')
  if not isinstance(event.get('note'),str) or not isinstance(event.get('order_note'),str):raise ValueError('事件需保留範圍與先後限制')
 if not isinstance(entries,list):raise ValueError('修復表缺少已核對回合')
 seen=set();groups=set();counted_records=set();anchors={'repair-summary'}
 canonical={rid:g['original_record_id'] for g in archive.get('edit_groups',[]) for rid in g['version_record_ids']}
 for e in entries:
  identity=e.get('id')
  if not isinstance(identity,str) or not identity.replace('-','').replace('_','').isalnum() or identity in seen:raise ValueError('修復回合ID須有效且唯一')
  seen.add(identity)
  anchor='repair-'+identity
  if anchor in anchors or anchor in event_ids or anchor in known:raise ValueError('修復錨點與既有分析或來源衝突')
  anchors.add(anchor)
  if e.get('event_id') not in event_ids or e.get('actor') not in ('self','other'):raise ValueError('修復事件或行為者不明')
  for key in ('phase','summary','rationale','outcome'):
   if not isinstance(e.get(key),str) or not e[key].strip():raise ValueError('修復判斷需有回合、理由及後續')
  group=(e['event_id'],e['actor'],e['phase'])
  if group in groups:raise ValueError('同一回合請合併分類，不重複計數')
  groups.add(group)
  cats=e.get('categories');styles=e.get('apology_styles');status=e.get('apology_status')
  if not isinstance(cats,list) or len(cats)!=len(set(cats)) or set(cats)-CATEGORIES.keys():raise ValueError('修復類別無效或重複')
  if not isinstance(styles,list) or len(styles)!=len(set(styles)) or set(styles)-STYLES.keys() or status not in STATUS:raise ValueError('道歉語意標記無效')
  if ('apology' in cats)!=(status in ('clear','limited')):raise ValueError('反諷、未知與非道歉不得混入有道歉')
  if e.get('initiative') not in INITIATIVES:raise ValueError('需分清主動發起、回應及未知')
  if e.get('source_kind') not in SOURCES:raise ValueError('修復來源種類不明')
  for key in ('record_ids','context_record_ids','outcome_record_ids'):
   ids=e.get(key)
   if not isinstance(ids,list) or len(ids)!=len(set(ids)) or any(i not in by_id for i in ids):raise ValueError('修復引用不存在或重複')
  if any(by_id[i]['speaker_role']!=e['actor'] for i in e['record_ids']):raise ValueError('修復行為者與原訊息說話者不符')
  if not isinstance(e.get('evidence_ids'),list) or not e['evidence_ids'] or any(i not in known for i in e['evidence_ids']):raise ValueError('修復缺少有效查核依據')
  if e['source_kind']=='message':
   if not e['record_ids'] or not e['context_record_ids']:raise ValueError('訊息修復須能定位原文及上下文')
   if cats:
    roots={canonical.get(i,i) for i in e['record_ids']}
    if roots & counted_records:raise ValueError('同一原訊息或其編輯版本被重複計為多個回合')
    counted_records.update(roots)
  elif e['record_ids']:raise ValueError('非訊息來源不得冒用訊息作已發生行為')
 for ev in coverage:
  for role,state in ev['status'].items():
   has=any(e['event_id']==ev['event_id'] and e['actor']==role and e['source_kind']=='message' and e['categories'] for e in entries)
   if (state=='confirmed')!=has:raise ValueError('事件狀態與明細不一致')
 return by_id

def statistics(review):
 """Count only already coded, message-grounded observations; categories overlap."""
 result={}
 for role in ('self','other'):
  es=[e for e in review['entries'] if e['actor']==role and e['source_kind']=='message']
  predicates={'rounds':lambda e:bool(e['categories']),**{key:(lambda e,key=key:key in e['categories']) for key in CATEGORIES},'initiated':lambda e:'goodwill' in e['categories'] and e['initiative']=='initiated','responded':lambda e:'goodwill' in e['categories'] and e['initiative']=='responded','conditional_or_negating':lambda e:any(s in e['apology_styles'] for s in ('conditional_exchange','negating')),'irony':lambda e:e['apology_status']=='irony','uncertain':lambda e:e['apology_status']=='uncertain'}
  for style in ('explanation','boundary','impact_qualified'):
   predicates['apology_'+style]=lambda e,style=style:'apology' in e['categories'] and style in e['apology_styles']
  result[role]={key:dict(rounds=sum(bool(test(e)) for e in es),events=len({e['event_id'] for e in es if test(e)})) for key,test in predicates.items()}
 return result

def render(review,events,archive,known,names):
 if review is None:return '',{},''
 by_id=validate(review,events,archive,known);stats=statistics(review)
 labels=[('rounds','修復次數（同一輪只算一次）'),('goodwill','示好或接住善意'),('initiated','其中：主動開口'),('responded','其中：回應另一方的善意'),('responsibility','承認自己的部分'),('adjustment','讓步或調整（包含答應下次怎麼做）'),('apology','有道歉（包含附帶解釋的）'),('apology_explanation','道歉時也解釋原因'),('apology_boundary','道歉但守住自己的界線'),('apology_impact_qualified','只為部分影響道歉'),('conditional_or_negating','另外記：附條件、說完又收回或推給別人'),('irony','另外記：聽起來像反話'),('uncertain','另外記：語氣還看不出來')]
 def number(role,key):
  x=stats[role][key]
  return f'{x["rounds"]} 次（{x["events"]} 個事件）' if x['rounds'] else '沒看到'
 table=''.join('<tr><th scope="row">'+esc(label)+'</th>'+''.join('<td>'+esc(number(role,key))+'</td>' for role in ('self','other'))+'</tr>' for key,label in labels)
 summary='<div class="repair-summary" id="repair-summary"><h3>行為統計：誰道歉誰示好</h3><p>'+esc(review['scope'])+'</p><p>'+esc(review['method'])+'</p><div class="repair-scroll"><table><thead><tr><th>項目</th><th>'+esc(names['self'])+'</th><th>'+esc(names['other'])+'</th></tr></thead><tbody>'+table+'</tbody></table></div><p class="repair-note">同一次修復可能同時算進好幾項，所以各項不能加總。像反話的、還不確定的、沒有訊息可查的，都不算進道歉。這些數字不代表誰比較愛、誰責任比較少，也不能拿來要求誰原諒誰。</p><details><summary>怎麼看道歉裡的「但是」和反話</summary><p>道歉時順便解釋原因、或保留不同意見，不代表道歉不算數；句子裡有「但是」「如果」「因為」，也不會直接當成假道歉。如果道歉要另一方先認錯才成立、說完馬上收回、聽起來像反話，或看不出在說什麼，會另外標出來並寫明理由。有沒有接受道歉、要不要原諒、會不會和好，是另外的事。每個事件下面都有細節可以回查。</p></details></div>'
 result={}
 for event in review['events']:
  eid=event['event_id'];es=[e for e in review['entries'] if e['event_id']==eid]
  status='；'.join(names[role]+'：'+('有看到' if event['status'][role]=='confirmed' else '沒看到，不代表沒做' if event['status'][role]=='not_confirmed' else '這次不算這一項') for role in ('self','other'))
  parts=[]
  for e in es:
   category='、'.join(CATEGORIES[c] for c in e['categories']) or STATUS[e['apology_status']]
   tags=[category,STATUS[e['apology_status']],SOURCES[e['source_kind']]]+[STYLES[s] for s in e['apology_styles']]
   if 'goodwill' in e['categories']:tags.append(INITIATIVES[e['initiative']])
   links=[]
   for n,rid in enumerate(e['record_ids']):links.append('<a href="#chat-record-'+attr(rid)+'">原文 '+str(n+1)+' · '+esc(by_id[rid]['timestamp'])+'</a>')
   for n,rid in enumerate(e['context_record_ids']):links.append('<a href="#chat-record-'+attr(rid)+'">'+('從前面看起' if n==0 else '看後面怎麼發展')+'</a>')
   for rid in e['outcome_record_ids']:links.append('<a href="#chat-record-'+attr(rid)+'">看'+esc(names['other' if e['actor']=='self' else 'self'])+'怎麼接</a>')
   links+=['<a class="ref" href="#'+attr(ref)+'">看依據</a>' for ref in e['evidence_ids']]
   parts.append('<details class="repair-entry" id="repair-'+attr(e['id'])+'"><summary>'+esc(names[e['actor']]+'｜'+e['phase'])+'</summary><p class="repair-tags">'+esc(' · '.join(dict.fromkeys(tags)))+'</p><p>'+esc(e['summary'])+'</p><p><strong>為什麼這樣算：</strong>'+esc(e['rationale'])+'</p><p><strong>後來：</strong>'+esc(e['outcome'])+'</p><div class="repair-links">'+''.join(links)+'</div></details>')
  body=''.join(parts) or '<p>這裡沒看到修復的過程，但不代表沒有發生過。</p>'
  result[eid]='<details class="repair-event"><summary>這次怎麼修復</summary><p>'+esc(status)+'</p><p>'+esc(event['note'])+'</p><p class="repair-order">'+esc(event['order_note'])+'</p>'+body+'</details>'
 return summary,result,STYLE
