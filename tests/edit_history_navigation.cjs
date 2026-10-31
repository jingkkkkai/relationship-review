// Synthetic DOM: test history deep links without a browser or private files.
const fs=require('fs'),vm=require('vm'),path=require('path');
const python=fs.readFileSync(path.join(__dirname,'../scripts/render_archive.py'),'utf8');
const source=python.match(/ARCHIVE_SCRIPT = '''([\s\S]*?)'''/)[1];
const events={},windowEvents={};
function element(id,tag='DIV',parent=null){return {id,tagName:tag,parentElement:parent,open:false,hidden:false,textContent:'',value:'',dataset:{},listeners:{},classList:{toggle(){}},setAttribute(){},addEventListener(k,f){this.listeners[k]=f},scrollIntoView(){this.scrolled=true}}}
const outer=element('outer'),root=element('conversation-review','DETAILS',outer);
const seg1=element('chat-segment-C1','DETAILS',root),seg2=element('chat-segment-C2','DETAILS',root);
seg1.dataset.categories=JSON.stringify(['日常與照顧']);seg1.textContent='舊版內容';
seg2.dataset.categories=JSON.stringify(['討論與磨合']);seg2.textContent='較晚的編輯';
const group=element('chat-message-R1','DIV',seg1),history=element('chat-edits-R1','DETAILS',group);
const old=element('chat-record-R1','DIV',history),latest=element('chat-record-R5','DIV',group);
const search=element('chat-search','INPUT'),count=element('chat-count');
const buttons=['','日常與照顧','討論與磨合'].map(filter=>{const b=element('','BUTTON');b.dataset.filter=filter;return b});
root.querySelectorAll=q=>q==='.segment'?[seg1,seg2]:buttons;
root.contains=target=>{for(let n=target;n;n=n.parentElement)if(n===root)return true;return false};
const all=[root,seg1,seg2,group,history,old,latest,search,count];
const document={getElementById:id=>all.find(n=>n.id===id),addEventListener(k,f){(events[k]??=[]).push(f)}};
const window={addEventListener(k,f){(windowEvents[k]??=[]).push(f)}},location={hash:''};
vm.runInNewContext(source,{document,window,location,requestAnimationFrame:fn=>fn()});
function click(id){const link={getAttribute:()=>`#${id}`};for(const f of events.click)f({target:{closest:()=>link},preventDefault(){}})}
function assert(condition,message){if(!condition)throw Error(message)}
buttons[2].listeners.click();search.value='較晚的編輯';search.listeners.input();assert(seg1.hidden,'Target should initially be filtered out');
click(old.id);assert(!seg1.hidden&&!search.value&&root.open&&seg1.open&&history.open&&old.scrolled,'Old-version link should clear filters and open history');
root.open=false;seg1.open=false;history.open=false;click(old.id);assert(root.open&&seg1.open&&history.open,'Same-hash link should reopen all ancestors');
history.open=false;click(latest.id);assert(!history.open&&latest.scrolled,'Latest version should remain visible without opening old history');
root.open=false;seg1.open=false;history.open=false;click(history.id);assert(root.open&&seg1.open&&history.open,'Relocated edit link should open the history at the original message');
console.log('PASS: exact-version and relocated edit links clear filters/search and open all required details; latest stays separate from folded history.');
