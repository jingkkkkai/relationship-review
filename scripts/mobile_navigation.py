"""Offline mobile return controls for generated reports."""

CSS='''
#mobile-return{display:none}#mobile-return[hidden]{display:none!important}
@media(max-width:760px),(hover:none) and (pointer:coarse){
 #mobile-return{display:flex;position:fixed;right:max(12px,env(safe-area-inset-right));bottom:calc(12px + env(safe-area-inset-bottom));z-index:20;gap:6px;padding:6px;border:1px solid #b8cfc0;border-radius:16px;background:#fffffff2;box-shadow:0 4px 20px #1e3c2b24;backdrop-filter:blur(10px)}
 #mobile-return button{min-height:44px;min-width:88px;padding:9px 12px;border:0;border-radius:10px;background:#e7f0e8;color:#245e4f;font:600 14px/1.4 system-ui,-apple-system,'PingFang TC',sans-serif;cursor:pointer}
 #mobile-return button:last-child{background:#286b60;color:white}
 #mobile-return button:focus-visible{outline:3px solid #bc8a39;outline-offset:3px}
 main{padding-bottom:calc(110px + env(safe-area-inset-bottom))!important}
 .stage-detail{scroll-margin-top:96px}
}
@media print{#mobile-return{display:none!important}}
'''
HTML='''<nav id="mobile-return" aria-label="手機閱讀位置導覽" hidden><button type="button" id="return-section" aria-label="回到目前事件、階段或對話片段的開頭">↑ 回本段</button><button type="button" id="return-top" aria-label="回到整份報告頂部">↑ 回頁首</button></nav>'''
SCRIPT='''(()=>{
const controls=document.getElementById('mobile-return');if(!controls)return;
const behavior=()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth';
const update=()=>{controls.hidden=window.scrollY<240;};
let pending=false;const schedule=()=>{if(pending)return;pending=true;requestAnimationFrame(()=>{pending=false;update();});};
window.addEventListener('scroll',schedule,{passive:true});window.addEventListener('resize',schedule);window.addEventListener('pageshow',schedule);
function currentSection(){
 const nav=document.querySelector('.quick-nav'),rect=nav?nav.getBoundingClientRect():null;
 const edge=rect&&rect.top<=1&&rect.bottom>0?rect.bottom+12:16;
 const selectors=['.conversation-review .segment','#event-review details[id]','.stage-detail','article[id]','#relationship-summary','#relationship-changes','#event-review','#conversation-review','#analysis-top'];
 for(const selector of selectors){for(const node of document.querySelectorAll(selector)){
  if(node.closest('[hidden]')||!node.getClientRects().length)continue;
  const r=node.getBoundingClientRect();if(r.top<=edge+1&&r.bottom>edge+1)return node;
 }}
 return document.getElementById('analysis-top');
}
document.getElementById('return-top').addEventListener('click',()=>window.scrollTo({top:0,behavior:behavior()}));
document.getElementById('return-section').addEventListener('click',()=>{const target=currentSection();if(target)target.scrollIntoView({block:'start',behavior:behavior()});});
update();
})();'''
HEAD='<!-- mobile-return-head:start --><style id="mobile-return-style">'+CSS+'</style><!-- mobile-return-head:end -->'
BODY='<!-- mobile-return-body:start -->'+HTML+'<script id="mobile-return-script">'+SCRIPT+'</script><!-- mobile-return-body:end -->'

def apply(out):
 if 'id="mobile-return"' in out:raise ValueError('Mobile controls already present; do not duplicate')
 return out.replace('</head>',HEAD+'</head>',1).replace('</body>',BODY+'</body>',1)
