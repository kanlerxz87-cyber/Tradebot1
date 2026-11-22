import {BASE,TOPICS,LABELS,DOCS,topicFor,price,qty,dollars,contractDollars,count,marketUrl,eventUrl,bookUrl,sample,qualifies,resolution,notional,eventGroups,normalizeBook,MoveDetector,csvCell} from './core.mjs';
import {emptyPaper,restorePaper,simulateAlert,settlePaper,paperSummary,STRATEGIES} from './paper.mjs';

const $=id=>document.getElementById(id);
const text=(id,value)=>{if($(id))$(id).textContent=value;};
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeUrl=value=>{try{const url=new URL(value);return url.protocol==='https:'?url.href:null;}catch{return null;}};
const sourceLink=(url,label='API ↗')=>`<a class="source-link" href="${esc(safeUrl(url)||DOCS.markets)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;
const toMs=value=>{if(value===null||value===undefined||value==='')return null;const n=typeof value==='number'?value:Date.parse(value);return Number.isFinite(n)?n:null;};
const utc=(value,seconds=false)=>{const ms=toMs(value);return ms===null?'—':new Date(ms).toLocaleString('en-GB',{month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit',...(seconds?{second:'2-digit'}:{}),timeZone:'UTC',hour12:false})+' UTC';};
const timeOnly=value=>new Date(value).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:'UTC',hour12:false});
const state={topic:document.body.dataset.topic||'all',view:document.body.dataset.view||'all',events:new Map(),markets:new Map(),histories:new Map(),alerts:[],series:new Map(),selected:null,range:'minutes',bookSide:'yes',book:null,chartPoints:[],chartSource:'Observed samples',adapter:false,backendActive:false,backendPaper:null,backendTickers:new Set(),stream:null,health:null,source:'No verified observations',updated:null,partial:true,loading:false,trackedLoading:false,roundRobin:0,query:'',sort:'contracts',visible:16,paused:false,storageError:false,detailVersion:0,paper:emptyPaper()};
const detector=new MoveDetector();
let lastBackendRender=0;

function storageRead(key){try{return JSON.parse(localStorage.getItem(key)||'null');}catch{return null;}}
function storageWrite(key,value){try{localStorage.setItem(key,JSON.stringify(value));}catch{state.storageError=true;}}
state.paper=restorePaper(storageRead('tradebot1-paper-v2'));
const saved=storageRead('tradebot1-observations-v2');
if(saved?.version===2 && Array.isArray(saved.events) && Array.isArray(saved.markets)) {
  for(const event of saved.events)if(event?.event_ticker&&topicFor(event))state.events.set(event.event_ticker,event);
  for(const market of saved.markets)if(market?.ticker&&state.events.has(market.event_ticker))state.markets.set(market.ticker,{...market,_meta:{...market._meta,kind:'retained'}});
}
function persist(){storageWrite('tradebot1-paper-v2',state.paper);storageWrite('tradebot1-observations-v2',{version:2,events:[...state.events.values()],markets:[...state.markets.values()]});}
async function fetchJson(url,timeout=10000){const response=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(timeout)});if(!response.ok)throw Error(`HTTP ${response.status}`);return response.json();}
async function publicRead(path,params={}) {
  const query=new URLSearchParams(params).toString();
  const suffix=path+(query?'?'+query:'');
  if(state.adapter)return fetchJson('/api/kalshi'+suffix);
  return fetchJson(BASE+suffix);
}
function status(message,type='pending'){text('connection',message);if($('connection'))$('connection').className='status '+type;}
function currentMarkets(){return [...state.markets.values()].filter(market=>{
  const event=state.events.get(market.event_ticker);
  return event&&(state.topic==='all'||topicFor(event)===state.topic);
});}
function filteredMarkets(){const query=state.query.trim().toLowerCase();return currentMarkets().filter(market=>market.status==='active'&&(!query||[market.ticker,market.title,market.yes_sub_title,state.events.get(market.event_ticker)?.title].some(value=>String(value||'').toLowerCase().includes(query))));}
function retainPoint(ticker,value,at,kind){if(value===null||at===null)return;let points=state.histories.get(ticker)||[];if(!points.some(p=>p.t===at&&p.v===value)){points.push({t:at,v:value,kind});points.sort((a,b)=>a.t-b.t);points=points.slice(-5000);state.histories.set(ticker,points);}}
function recordMarket(raw,event,kind='rest',at=Date.now()) {
  if(!raw?.ticker||!event?.event_ticker||!topicFor(event))return;
  const observed=toMs(at);
  const previous=state.markets.get(raw.ticker);
  if(previous?._meta?.observedAt&&observed!==null&&observed<previous._meta.observedAt)return;
  const market={...raw,event_ticker:raw.event_ticker||event.event_ticker,_meta:{kind,observedAt:observed,quoteAt:toMs(raw.quote_observed_ms)||observed}};
  state.events.set(event.event_ticker,event);state.markets.set(market.ticker,market);
  // A snapshot keeps its source timestamp and is NEVER an alert baseline or paper fill.
  const value=sample(market);
  if(qty(market.volume_fp)!==0)retainPoint(market.ticker,value,observed,kind);
  if(kind==='rest'&&market.status==='active'&&qty(market.volume_fp)!==0&&observed!==null) {
    const move=detector.observe(market.ticker,value,observed);
    if(move) {
      const alert={id:`browser:${market.ticker}:${observed}`,ticker:market.ticker,eventTicker:market.event_ticker,topic:topicFor(event),title:market.title||event.title,...move,selected:qualifies(market),kind:'REST sample',model:null,source_url:market.source_url||marketUrl(market.ticker),catalysts:[]};
      state.alerts.unshift(alert);state.alerts=state.alerts.slice(0,200);
      if(simulateAlert(state.paper,alert,market,event,Date.now()))storageWrite('tradebot1-paper-v2',state.paper);
    }
  }
  if(settlePaper(state.paper,market))storageWrite('tradebot1-paper-v2',state.paper);
}
function renderStats(){
  const rows=filteredMarkets(),events=new Set(rows.map(m=>m.event_ticker)),alerts=state.alerts.filter(a=>state.topic==='all'||a.topic===state.topic);
  text('stat-events',events.size.toLocaleString());text('stat-markets',rows.length.toLocaleString());text('stat-alerts',alerts.length.toLocaleString());text('row-count',rows.length);
  const groups=eventGroups(rows,state.events,'notional');
  const complete=groups.length&&groups.every(group=>group.notional!==null&&!group.event.markets_partial);
  text('stat-notional',complete?dollars(groups.reduce((sum,group)=>sum+group.notional,0),true):'—');
  text('notional-note',complete?'Cumulative notional · not cash turnover':'Not reported for every observed contract');
  for(const el of document.querySelectorAll('[data-topic-count]')){const topic=el.dataset.topicCount;el.textContent=new Set([...state.markets.values()].filter(m=>m.status==='active'&&(topic==='all'||topicFor(state.events.get(m.event_ticker))===topic)).map(m=>m.event_ticker)).size;}
  const updated=state.updated?utc(state.updated):'no confirmed timestamp';
  text('coverage',`${state.source} · ${updated} · ${state.partial?'bounded coverage':'complete discovery pages, local topic rules'}`);
  text('table-note',state.sort==='notional'?'Reported cumulative dollar notional only. Blanks rank after known values; 24h contracts break ties.':'Sorted by reported 24h contract count, not dollars. Switch to $ notional when reported values are available.');
  if(state.storageError)text('data-mode','Browser storage is unavailable/full. Persistent tracking requires the trusted service; existing rows are retained in memory.');
}
function renderTable(){
  if(!$('market-rows'))return;
  const groups=eventGroups(filteredMarkets(),state.events,state.sort);let shown=0,html='';
  for(const group of groups){if(shown>=state.visible)break;const {event}=group,topic=topicFor(event);
    html+=`<tr class="event-row"><td colspan="7"><div class="event-heading"><span class="topic-dot ${esc(topic)}">${esc({gas:'◈',elections:'▧',culture:'✧',crypto:'₿',golf:'⚑'}[topic]||'·')}</span><strong>${esc(event.title||event.event_ticker)}</strong>${sourceLink(event.source_url||eventUrl(event.event_ticker),'Event ↗')}</div></td></tr>`;
    for(const market of [...group.markets].sort((a,b)=>(qty(b.volume_24h_fp)??-1)-(qty(a.volume_24h_fp)??-1))){if(shown>=state.visible)break;shown++;
      html+=`<tr class="event-child ${market.ticker===state.selected?'selected':''}"><td><button class="market-link" data-select="${esc(market.ticker)}">${esc(market.yes_sub_title||market.title||market.ticker)}</button><small class="ticker" title="${esc(market.ticker)}">${esc(market.ticker)}</small></td><td class="num price-value">${contractDollars(sample(market))}</td><td class="num">${contractDollars(price(market.yes_bid_dollars))} <span class="muted">/</span> ${contractDollars(price(market.yes_ask_dollars))}</td><td class="num">${count(qty(market.volume_24h_fp))}</td><td class="num" title="Exchange-reported cumulative notional; blank if not reported">${dollars(notional(market),true)}</td><td><span class="state-tag ${esc(market.status)}">${esc(market.status||'Unverified')}</span></td><td>${sourceLink(market.source_url||marketUrl(market.ticker))}<small>${market._meta?.kind==='snapshot'?'Snapshot':'Observed'}</small></td></tr>`;
    }
  }
  $('market-rows').innerHTML=html||`<tr><td colspan="7" class="empty">${state.query?'No observed contracts match that search.':'No source-confirmed contracts for this topic in the current sample.'}<br>A blank is not a zero. ${sourceLink(DOCS.events,'Official event documentation ↗')}</td></tr>`;
  for(const button of document.querySelectorAll('[data-select]'))button.addEventListener('click',()=>selectMarket(button.dataset.select));
  if($('show-more')){$('show-more').hidden=shown>=filteredMarkets().length;$('show-more').textContent=`Show more contracts (${Math.max(0,filteredMarkets().length-shown)} remaining) ↓`;}
}
function renderFeeds(){
  if(!$('all-feed')||state.paused)return;
  const alerts=state.alerts.filter(a=>state.topic==='all'||a.topic===state.topic);
  const selected=alerts.filter(a=>a.selected);text('all-count',alerts.length);text('screen-count',`${selected.length} signals`);
  text('model-caption',state.backendActive?'Prior observations + executable depth. Unvalidated.':'Quote-size / spread screen. No ROI estimate.');
  for(const [id,items] of [['all-feed',alerts],['screen-feed',selected]]){
    const feed=$(id),scroll=feed.scrollTop;
    feed.innerHTML=items.length?items.slice(0,100).map(alert=>{
      const up=alert.change>0;const model=alert.model;
      return `<article class="feed-item"><div class="feed-top"><span class="move-badge ${up?'':'down'}">${up?'↗ +':'↘ −'}${Math.abs(alert.change).toFixed(2)}</span><span class="eyebrow">${esc(LABELS[alert.topic]||alert.topic)}</span><time datetime="${new Date(alert.at).toISOString()}">${timeOnly(alert.at)} UTC</time></div><strong>${esc(alert.title||alert.ticker)}</strong><small>${contractDollars(alert.from)} → ${contractDollars(alert.to)} · ${esc(alert.kind||'observed update')}</small>${model?`<small>Hypothesis: ${esc(model.strategy?.replaceAll('_',' '))} · ${esc(model.outcome?.toUpperCase())} · gross edge ${dollars(model.gross_edge_dollars)}. Fees unknown.</small>`:''}${sourceLink(alert.source_url||marketUrl(alert.ticker),'Market evidence ↗')}<small>No verified causal publication linked to this move.</small></article>`;
    }).join(''):`<div class="feed-empty"><div class="empty-glyph">${id==='all-feed'?'⌁':'✧'}</div><strong>${id==='all-feed'?'Listening for the next move':'Waiting for a qualifying signal'}</strong><p>${id==='all-feed'?'A move of at least 10¢ in either direction appears here. Published snapshots never create alerts.':'Selection is a research hypothesis, not proof of high ROI. Missing data never becomes a signal.'}</p></div>`;
    if(scroll>10)feed.scrollTop=scroll; // readers inspecting older chat are not yanked to the top
  }
}
function localPaper(){return paperSummary(state.paper,state.markets);}
function paperRows(){
  if(state.backendPaper?.accounts){return Object.entries(state.backendPaper.accounts).flatMap(([strategy,account])=>(account.positions||[]).map(p=>({ticker:p.ticker,topic:p.topic,strategy,side:p.outcome,count:p.count,entry:p.average_price,at:p.timestamp_ms,status:p.status,result:p.result,grossPnl:p.gross_pnl??p.realized_gross_pnl,source_url:p.source_url,assumption:'Server depth-based hypothetical fill'})));}
  return Object.values(localPaper().accounts).flatMap(account=>account.positions);
}
function renderPaper(){
  const rows=paperRows().filter(p=>state.topic==='all'||p.topic===state.topic).sort((a,b)=>b.at-a.at);
  if($('paper-rows'))$('paper-rows').innerHTML=rows.length?rows.slice(0,state.view==='portfolio'?500:8).map(p=>`<tr><td>${esc(p.strategy.replaceAll('_',' '))}<small>${esc(LABELS[p.topic]||p.topic)} · hypothetical</small></td><td><span class="ticker">${esc(p.ticker)}</span><small>${utc(p.at)}</small></td><td>${esc(p.side.toUpperCase())} / ${count(p.count)}</td><td class="num">${contractDollars(p.entry)}</td><td>${esc(p.result?.toUpperCase()||p.status)}</td><td class="num ${p.grossPnl!==null&&Number(p.grossPnl)<0?'down':'up'}">${dollars(p.grossPnl)}</td><td>${sourceLink(p.source_url||marketUrl(p.ticker))}</td></tr>`).join(''):`<tr><td colspan="7" class="empty">No hypothetical fills yet. Strategies wait for observed swings and confirmed quote size.<br>${sourceLink(DOCS.orderbook,'Liquidity specification ↗')}</td></tr>`;
  text('paper-summary',`${rows.length} hypothetical entries · ${state.backendPaper?.accounts?'persistent server':'this browser'} ledger · gross only; fees and net ROI unverified`);
  if($('analysis-rows')){
    const groups=new Map();
    for(const row of rows){const key=`${row.topic}:${row.strategy}:${row.side}`;if(!groups.has(key))groups.set(key,{topic:row.topic,strategy:row.strategy,side:row.side,rows:[]});groups.get(key).rows.push(row);}
    $('analysis-rows').innerHTML=[...groups.values()].map(group=>{const settled=group.rows.filter(p=>p.status==='settled');const realized=settled.every(p=>p.grossPnl!==null&&p.grossPnl!==undefined)?settled.reduce((sum,p)=>sum+Number(p.grossPnl),0):null;return `<tr><td>${esc(LABELS[group.topic]||group.topic)}</td><td>${esc(group.strategy.replaceAll('_',' '))}</td><td>${esc(group.side.toUpperCase())}</td><td class="num">${group.rows.length}</td><td class="num">${settled.length}</td><td class="num">${dollars(realized)}</td><td>${sourceLink(group.rows[0].source_url||marketUrl(group.rows[0].ticker),'Underlying record ↗')}<small>Local hypothetical aggregate</small></td></tr>`;}).join('')||`<tr><td colspan="7" class="empty">No hypothetical entries to group. No performance results have been invented.<br>${sourceLink(DOCS.portfolio,'Account performance specification ↗')}</td></tr>`;
  }
  if($('strategy-cards')){
    const local=localPaper();
    $('strategy-cards').innerHTML=STRATEGIES.map(strategy=>{
      const backend=state.backendPaper?.accounts?.[strategy];
      const account=backend?{cash:backend.cash,grossEquity:backend.gross_equity,positions:backend.positions}:local.accounts[strategy];
      return `<article class="panel strategy-card"><div class="eyebrow">HYPOTHESIS ${strategy==='momentum'?'01':'02'}</div><h3>${strategy==='momentum'?'Momentum':'Mean reversion'}</h3><p>${strategy==='momentum'?'Follow the direction of an observed price swing.':'Test a reversal after an observed price swing.'} No validated edge is assumed.</p><div class="strategy-stats"><div><label>Simulated cash</label><strong>${dollars(account.cash)}</strong></div><div><label>Gross equity</label><strong>${dollars(account.grossEquity)}</strong></div><div><label>Paper entries</label><strong>${account.positions.length}</strong></div></div><small>$1,000 starting cash is a simulation assumption. Fees, net ROI and real execution are unverified. ${sourceLink(DOCS.orders,'Execution specification ↗')}</small></article>`;
    }).join('');
  }
}
function renderLifecycle(){
  if(!$('resolution-rows'))return;const rows=currentMarkets().filter(m=>m.status!=='active');
  $('resolution-rows').innerHTML=rows.length?rows.map(m=>`<tr><td>${esc(state.events.get(m.event_ticker)?.title||m.event_ticker)}<small class="ticker">${esc(m.ticker)}</small></td><td><span class="state-tag ${esc(m.status)}">${esc(m.status||'Unknown')}</span></td><td>${resolution(m)||'—'}${m.result==='scalar'?'<small>Scalar — review required</small>':''}</td><td>${sourceLink(m.source_url||marketUrl(m.ticker))}</td></tr>`).join(''):`<tr><td colspan="4" class="empty">No closed or finalized contracts observed in this tracked set. Determination is not final settlement.<br>${sourceLink('https://docs.kalshi.com/getting_started/market_lifecycle','Official lifecycle ↗')}</td></tr>`;
}
function renderBook(){
  if(!$('book-rows'))return;
  if(!state.book){$('book-rows').innerHTML=`<tr><td colspan="3" class="empty">No confirmed orderbook available.<br>${sourceLink(DOCS.orderbook,'Orderbook specification ↗')}</td></tr>`;text('book-time','Unavailable · no levels inferred');return;}
  const book=state.book,bids=state.bookSide==='yes'?book.yesBids:book.noBids,asks=state.bookSide==='yes'?book.yesAsks:book.noAsks;
  const max=Math.max(1,...[...bids,...asks].map(level=>level.quantity));
  const cell=(level,ask=false)=>level?`<td class="num"><span class="depth-bar ${ask?'ask':''}" style="width:${Math.min(100,level.quantity/max*100).toFixed(2)}%"></span><span class="depth-label ${ask?'ask-text':'bid-text'}">${contractDollars(level.price)} <span class="muted">/ ${count(level.quantity)}</span></span></td>`:'<td class="num">—</td>';
  $('book-rows').innerHTML=Array.from({length:Math.min(7,Math.max(bids.length,asks.length))},(_,i)=>`<tr>${cell(bids[i])}${cell(asks[i],true)}<td>${sourceLink(book.source,'↗')}</td></tr>`).join('')||`<tr><td colspan="3" class="empty">No resting levels reported. ${sourceLink(book.source)}</td></tr>`;
  text('book-time',`${book.published?'Published snapshot':'Observed'} ${utc(book.observedAt,true)}${book.published?' · NOT current liquidity':Date.now()-book.observedAt>15000?' · stale':''}`);
}
function plot(){
  const svg=$('chart');if(!svg)return;svg.replaceChildren();
  const ns='http://www.w3.org/2000/svg';const add=(tag,attrs={},content,parent=svg)=>{const el=document.createElementNS(ns,tag);for(const [key,value]of Object.entries(attrs))el.setAttribute(key,value);if(content!==undefined)el.textContent=content;parent.append(el);return el;};
  const width=760,height=260,left=48,right=735,top=12,bottom=224;
  for(let i=0;i<=4;i++){const y=top+i*(bottom-top)/4;add('line',{x1:left,y1:y,x2:right,y2:y,stroke:'#26373a','stroke-dasharray':'3 6','stroke-width':1});add('text',{x:1,y:y+4,fill:'#698585','font-size':10,'font-family':'monospace'},'$'+(1-i*.25).toFixed(2));}
  const all=state.chartPoints.length?state.chartPoints:(state.histories.get(state.selected)||[]);
  const market=state.markets.get(state.selected),snapshot=market?._meta?.kind==='snapshot'||market?._meta?.kind==='retained';
  const end=snapshot&&all.length?Math.max(...all.map(point=>point.t)):Date.now();const duration={seconds:60000,minutes:3600000,hours:86400000}[state.range];const start=end-duration;
  const points=all.filter(p=>Number.isFinite(p.t)&&price(p.v)!==null&&p.t>=start&&p.t<=end).sort((a,b)=>a.t-b.t);
  for(let i=0;i<5;i++){const t=start+duration*i/4;add('text',{x:left+(right-left)*i/4,y:height-9,fill:'#698585','font-size':9,'text-anchor':i===4?'end':i===0?'start':'middle','font-family':'monospace'},state.range==='hours'?timeOnly(t).slice(0,5):timeOnly(t));}
  if(!points.length){add('text',{x:width/2,y:112,fill:'#829d94','font-size':12,'text-anchor':'middle'},'Price history starts with verified observations.');add('text',{x:width/2,y:134,fill:'#5f7e7b','font-size':10,'text-anchor':'middle'},'No samples are invented to fill the chart.');text('chart-caption','No confirmed points in this window. Seconds = 1m · minutes = 1h · hours = 24h.');return;}
  const x=p=>left+(p.t-start)/duration*(right-left),y=p=>bottom-p.v*(bottom-top);
  if(points.length>1){const defs=add('defs');const gradient=add('linearGradient',{id:'price-fill',x1:'0',y1:'0',x2:'0',y2:'1'},undefined,defs);add('stop',{offset:'0%','stop-color':'#a4d97d','stop-opacity':'.16'},undefined,gradient);add('stop',{offset:'100%','stop-color':'#a4d97d','stop-opacity':'.005'},undefined,gradient);const path=points.map((p,i)=>`${i?'L':'M'}${x(p).toFixed(2)},${y(p).toFixed(2)}`).join(' ');add('path',{d:path+` L${x(points.at(-1))},${bottom} L${x(points[0])},${bottom} Z`,fill:'url(#price-fill)'});add('path',{d:path,stroke:'#b3e981','stroke-width':2,fill:'none','stroke-linejoin':'round','stroke-linecap':'round'});}
  for(const point of points.slice(-200)){const circle=add('circle',{cx:x(point),cy:y(point),r:points.length===1?4:2,fill:'#b3e981',stroke:'#172820','stroke-width':1});add('title',{},`${utc(point.t,true)} · ${contractDollars(point.v)} · ${point.kind||state.chartSource}`,circle);}
  const move=state.alerts.filter(a=>a.ticker===state.selected&&a.at>=start&&a.at<=end);
  for(const alert of move){const p={t:alert.at,v:alert.to};const marker=add('circle',{cx:x(p),cy:y(p),r:5,fill:alert.change>0?'#b3e981':'#e6a29b',stroke:'#111b1e','stroke-width':2});add('title',{},`Observed ${alert.change>0?'+':''}${alert.change.toFixed(2)} move. Cause unverified.`,marker);}
  const cross=add('line',{x1:0,x2:0,y1:top,y2:bottom,stroke:'#63805c','stroke-dasharray':'3 4',visibility:'hidden'});
  const hit=add('rect',{x:left,y:top,width:right-left,height:bottom-top,fill:'transparent'});
  hit.addEventListener('pointermove',event=>{const bounds=svg.getBoundingClientRect(),px=(event.clientX-bounds.left)/bounds.width*width;const nearest=points.reduce((best,p)=>Math.abs(x(p)-px)<Math.abs(x(best)-px)?p:best,points[0]);cross.setAttribute('x1',x(nearest));cross.setAttribute('x2',x(nearest));cross.setAttribute('visibility','visible');if($('chart-tooltip')){$('chart-tooltip').hidden=false;text('chart-tooltip',`${utc(nearest.t,true)} · YES ${contractDollars(nearest.v)}`);}});
  hit.addEventListener('pointerleave',()=>{cross.setAttribute('visibility','hidden');if($('chart-tooltip'))$('chart-tooltip').hidden=true;});
  text('chart-caption',`${points.length} actual observations · ${state.chartSource}${snapshot?' · historical snapshot, not live':''}. Lines connect samples; intervening prices are unknown.`);
}
function renderDetail(){const market=state.markets.get(state.selected),event=state.events.get(market?.event_ticker);if(!market||!event||!$('detail-title')){plot();return;}text('detail-title',event.title||market.title||market.ticker);text('detail-sub',market.ticker);text('detail-topic',LABELS[topicFor(event)]||'CONTRACT');text('detail-price',contractDollars(sample(market)));text('detail-meta',`YES · ${market._meta?.kind==='snapshot'?'snapshot':'observed'} ${utc(market._meta?.observedAt)}`);$('detail-source').href=safeUrl(market.source_url)||marketUrl(market.ticker);$('event-source').href=safeUrl(event.source_url)||eventUrl(event.event_ticker);text('rule-text',market.rules_primary||'No primary rule text supplied in this observation. Check the official market and event sources.');const links=$('settlement-sources');if(links){links.replaceChildren();for(const source of (event.settlement_sources||[]).slice(0,5)){const url=safeUrl(source.url);if(!url)continue;const a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=(source.name||'Listed settlement source')+' ↗';links.append(a);}if(!links.children.length)links.textContent='No verified settlement source supplied in this response.';}plot();}
async function loadHistory(ticker,version){
  const fallback=state.markets.get(ticker)?.history_snapshots?.[state.range];
  state.chartPoints=(fallback?.candlesticks||[]).map(c=>({t:c.end_period_ts*1000,v:price(c.price?.close_dollars),kind:'published official candle close'})).filter(p=>p.v!==null&&Number.isFinite(p.t));
  state.chartSource=fallback?`Published ${state.range==='hours'?'hourly':'minute'} candle closes · ${utc(fallback.observed_at)}`:'Source-timestamped observations';plot();
  try{
    if(state.adapter&&state.backendTickers.has(ticker)){const data=await fetchJson(`/api/markets/${encodeURIComponent(ticker)}/history?window=${state.range}`);if(version!==state.detailVersion)return;state.chartPoints=(data.points||[]).map(p=>({t:p.timestamp_ms,v:price(p.price_dollars),kind:p.kind})).filter(p=>p.v!==null);state.chartSource='Persisted demo observations';plot();return;}
    if(state.range==='seconds')return;
    const event=state.events.get(state.markets.get(ticker)?.event_ticker);if(!event?.series_ticker)return;
    const end=Math.floor(Date.now()/1000),period=state.range==='hours'?60:1;const data=await publicRead(`/series/${encodeURIComponent(event.series_ticker)}/markets/${encodeURIComponent(ticker)}/candlesticks`,{start_ts:end-(period===60?86400:3600),end_ts:end,period_interval:period});
    if(version!==state.detailVersion)return;state.chartPoints=(data.candlesticks||[]).map(c=>({t:c.end_period_ts*1000,v:price(c.price?.close_dollars),kind:'official candle close'})).filter(p=>p.v!==null);state.chartSource=`Kalshi ${period===60?'hourly':'minute'} candle closes`;plot();
  }catch{if(version===state.detailVersion){if(!fallback)state.chartSource='Observed points only; exchange history unavailable';plot();}}
}
async function loadBook(ticker,version){
  const fallback=state.markets.get(ticker)?.orderbook_snapshot;
  const fallbackBook=fallback?normalizeBook(fallback,toMs(fallback.observed_at),fallback.source_url):null;
  if(fallbackBook){fallbackBook.published=true;if(version===state.detailVersion){state.book=fallbackBook;renderBook();}}
  try{
  let book;
  if(state.adapter&&state.backendTickers.has(ticker)){const data=await fetchJson(`/api/markets/${encodeURIComponent(ticker)}/orderbook`);const levels=rows=>(rows||[]).map(p=>({price:price(p.price_dollars),quantity:qty(p.contracts)})).filter(p=>p.price!==null&&p.quantity!==null);book=data.valid&&!data.stale?{yesBids:levels(data.yes_bids),noBids:levels(data.no_bids),yesAsks:levels(data.yes_asks),noAsks:levels(data.no_asks),observedAt:data.observed_ms,source:data.source_url}:null;}
  else book=normalizeBook(await publicRead(`/markets/${encodeURIComponent(ticker)}/orderbook`,{depth:7}),Date.now(),bookUrl(ticker));
  if(version===state.detailVersion){state.book=book;renderBook();}
}catch{if(version===state.detailVersion){state.book=fallbackBook;renderBook();}}}
function selectMarket(ticker){state.selected=ticker;state.book=null;state.chartPoints=[];state.detailVersion++;const version=state.detailVersion;renderTable();renderDetail();renderBook();loadHistory(ticker,version);loadBook(ticker,version);}
function render(){renderStats();renderTable();renderFeeds();renderPaper();renderLifecycle();renderDetail();}
function maybeSelect(){
  if(!$('chart')||state.selected&&filteredMarkets().some(m=>m.ticker===state.selected))return;
  const candidates=filteredMarkets();
  const hasCandles=(market,range)=>(market.history_snapshots?.[range]?.candlesticks||[]).filter(c=>price(c.price?.close_dollars)!==null).length>1;
  const minuteCandidates=candidates.filter(m=>hasCandles(m,'minutes'));
  const withHistory=minuteCandidates.length?minuteCandidates:candidates.filter(m=>hasCandles(m,'hours'));
  const first=withHistory.sort((a,b)=>(qty(b.volume_24h_fp)||0)-(qty(a.volume_24h_fp)||0))[0]||eventGroups(candidates,state.events,state.sort)[0]?.markets[0];
  if(first){
    if(!hasCandles(first,state.range)&&hasCandles(first,'hours')){state.range='hours';for(const button of document.querySelectorAll('[data-range]')){const active=button.dataset.range===state.range;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));}}
    selectMarket(first.ticker);
  }else{state.selected=null;state.chartPoints=[];state.book=null;renderBook();plot();}
}
async function loadSnapshot(){
  try{const data=await fetchJson(new URL('../data/snapshot.json',import.meta.url));const generated=toMs(data.generated_at);for(const event of data.events||[])if(topicFor(event))for(const market of event.markets||[])recordMarket(market,event,'snapshot',toMs(market.observed_at)||toMs(event.observed_at)||generated);
    if(generated){state.source='Published official API snapshot';state.updated=generated;state.partial=true;text('data-mode',`Published snapshot · ${utc(generated)} · not a live feed`);status('Snapshot · not live','pending');}
    else{text('data-mode','No confirmed public snapshot available. Unverified values stay blank.');status('No verified feed','pending');}
    if(data.last_refresh_error)text('data-mode',`Snapshot refresh failed; retaining original timestamps. ${data.generated_at?utc(data.generated_at):'No previous verified snapshot.'}`);
  }catch{text('data-mode','Source snapshot unavailable. No sample prices have been substituted.');status('Source unavailable','error');}
  render();maybeSelect();
}
function consumeBackend(data){
  if(!data?.health)return;state.health=data.health;state.backendTickers=new Set((data.markets||[]).map(m=>m.ticker));
  const active=!data.health.data_stale&&['polling','partial'].includes(data.health.rest)||data.health.websocket==='connected'&&!data.health.data_stale;
  state.backendActive=Boolean(active);state.backendPaper=data.paper||null;
  if(data.markets?.length){const eventMap=new Map((data.events||[]).map(e=>[e.event_ticker,e]));for(const market of data.markets){const event=eventMap.get(market.event_ticker);if(event)recordMarket(market,event,'backend',market.price_observed_ms||market.observed_ms);}
    state.alerts=(data.alerts||[]).map(a=>({id:a.id,ticker:a.ticker,topic:a.topic,title:a.title,from:price(a.from_price),to:price(a.to_price),change:Number(a.delta_dollars),at:a.timestamp_ms,selected:a.selected,model:a.model,source_url:a.source_url,kind:a.observation_kind,catalysts:a.catalysts||[]})).filter(a=>a.from!==null&&a.to!==null&&Number.isFinite(a.change)&&Number.isFinite(a.at));
    state.source=data.health.websocket==='connected'?'Authenticated demo trade stream':'Server demo REST observations';state.updated=toMs(data.health.last_stream_message)||toMs(data.health.last_rest_success);state.partial=!data.health.discovery_complete;
  }
  if(active){status(data.health.websocket==='connected'?'Demo stream connected':'Demo REST · sampled','ok');text('data-mode',data.health.websocket==='connected'?'Authenticated demo stream · public market data only · no account values exposed':'Trusted service · sampled demo REST observations, not tick-by-tick streaming');text('feed-mode',data.health.websocket==='connected'?'Demo trade stream':'Server REST samples');}
  else{if(!state.markets.size)text('data-mode','Service available; Kalshi network/account not connected. No market values fabricated.');status(state.updated?'Snapshot / stale observations':'Feed disconnected','pending');text('feed-mode','No current exchange stream');}
  if(Date.now()-lastBackendRender>250){render();maybeSelect();lastBackendRender=Date.now();}
}
async function detectService(){try{const health=await fetchJson('/api/health',2000);if(health.mode!=='demo_only')return;state.adapter=true;state.health=health;consumeBackend(await fetchJson('/api/snapshot'));state.stream=new EventSource('/api/stream');for(const event of ['snapshot','update'])state.stream.addEventListener(event,message=>{try{consumeBackend(JSON.parse(message.data));}catch{status('Feed payload invalid','error');}});state.stream.onerror=()=>{state.backendActive=false;status('Feed reconnecting','pending');};}catch{/* A static Pages deployment legitimately has no same-origin service. */}}
async function discover(){
  if(state.loading)return;state.loading=true;if($('refresh'))$('refresh').disabled=true;
  if(state.adapter){try{consumeBackend(await fetchJson('/api/snapshot'));}catch{status('Service unavailable','error');}finally{state.loading=false;if($('refresh'))$('refresh').disabled=false;}return;}
  status('Checking demo REST','pending');
  try{
    if(!state.series.size){const data=await publicRead('/series');if(!Array.isArray(data.series))throw Error('Series unavailable');for(const series of data.series)if(series?.ticker)state.series.set(series.ticker,series);}
    let cursor='',pages=0;const seen=new Set();let observed=0;
    do{const data=await publicRead('/events',{status:'open',with_nested_markets:'true',limit:200,...(cursor?{cursor}:{})});if(!Array.isArray(data.events))throw Error('Events unavailable');for(const rawEvent of data.events){const series=state.series.get(rawEvent.series_ticker);const event={...rawEvent,series_metadata:series,settlement_sources:rawEvent.settlement_sources||series?.settlement_sources||[],series_source_url:series?.ticker?`${BASE}/series/${encodeURIComponent(series.ticker)}`:null,source_url:eventUrl(rawEvent.event_ticker)};if(!topicFor(event))continue;for(const market of event.markets||[]){recordMarket(market,event,'rest',Date.now());observed++;}}
      if(data.cursor===undefined)throw Error('Pagination unverified');cursor=data.cursor;pages++;if(cursor&&seen.has(cursor))throw Error('Repeated pagination cursor');if(cursor)seen.add(cursor);
    }while(cursor&&pages<4);
    state.source=`Browser demo REST · ${pages} event pages`;state.partial=Boolean(cursor);state.updated=Date.now();status('Demo REST · sampled','ok');text('data-mode',`Public demo REST · ${observed} contract observations in this scan · not tick-by-tick`);text('feed-mode','REST observations · sampled every 20s');persist();render();maybeSelect();
  }catch{status(state.updated?'Snapshot · REST unavailable':'REST unavailable','pending');text('data-mode',state.updated?`Showing source-timestamped observations from ${utc(state.updated)}. Live REST unavailable (network/CORS/rate limit).`:'Kalshi REST unavailable. No prices, balances or outcomes have been invented.');}
  finally{state.loading=false;if($('refresh'))$('refresh').disabled=false;}
}
async function refreshTracked(){
  if(state.loading||state.trackedLoading)return;
  if(state.backendActive){if(state.selected){loadBook(state.selected,state.detailVersion);loadHistory(state.selected,state.detailVersion);}return;}
  if(state.adapter)return;
  const unresolved=[...state.markets.values()].filter(m=>m.status!=='finalized').map(m=>m.ticker);
  if(!unresolved.length)return;state.trackedLoading=true;
  const offset=state.roundRobin%unresolved.length;const batch=[...new Set([state.selected,...unresolved.slice(offset),...unresolved.slice(0,offset)].filter(Boolean))].slice(0,100);state.roundRobin+=99;
  try{const data=await publicRead('/markets',{tickers:batch.join(',')});if(!Array.isArray(data.markets))throw Error('Missing markets');const seen=new Set();for(const market of data.markets){seen.add(market.ticker);const event=state.events.get(market.event_ticker);if(event)recordMarket(market,event,'rest',Date.now());}
    // Missing tickers stay retained. An unavailable endpoint is not evidence of resolution.
    state.updated=Date.now();state.source='Browser demo REST · retained watchlist';state.partial=true;status('Demo REST · sampled','ok');text('data-mode',`Public demo REST · ${seen.size}/${batch.length} watched contracts refreshed · timestamps are observations`);text('feed-mode',`REST samples · ${unresolved.length} unresolved contracts retained`);persist();render();if(state.selected)loadBook(state.selected,state.detailVersion);
  }catch{status('Last observations · feed stale','pending');}finally{state.trackedLoading=false;}
}
function exportData(){const headers=['event_ticker','ticker','topic','last_yes_price','yes_bid','yes_ask','volume_24h_contracts','reported_cumulative_dollar_notional','status','final_result','observed_at','source_kind','source_url'];const rows=currentMarkets().map(m=>[m.event_ticker,m.ticker,topicFor(state.events.get(m.event_ticker)),sample(m),price(m.yes_bid_dollars),price(m.yes_ask_dollars),qty(m.volume_24h_fp),notional(m),m.status,resolution(m),m._meta?.observedAt?new Date(m._meta.observedAt).toISOString():null,m._meta?.kind,m.source_url||marketUrl(m.ticker)]);const csv=[headers,...rows].map(row=>row.map(csvCell).join(',')).join('\r\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`kalshi-demo-observations-${new Date().toISOString().slice(0,10)}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('refresh')?.addEventListener('click',discover);$('export')?.addEventListener('click',exportData);
$('search')?.addEventListener('input',event=>{state.query=event.target.value;state.visible=16;renderStats();renderTable();});
$('sort')?.addEventListener('change',event=>{state.sort=event.target.value;renderStats();renderTable();});
$('show-more')?.addEventListener('click',()=>{state.visible+=24;renderTable();});
$('pause')?.addEventListener('click',()=>{state.paused=!state.paused;$('pause').setAttribute('aria-pressed',String(state.paused));text('pause',state.paused?'Resume feed display':'Pause feed display');if(!state.paused)renderFeeds();});
for(const button of document.querySelectorAll('[data-range]'))button.addEventListener('click',()=>{state.range=button.dataset.range;for(const other of document.querySelectorAll('[data-range]')){const active=other===button;other.classList.toggle('active',active);other.setAttribute('aria-pressed',String(active));}state.detailVersion++;loadHistory(state.selected,state.detailVersion);});
for(const button of document.querySelectorAll('[data-book-side]'))button.addEventListener('click',()=>{state.bookSide=button.dataset.bookSide;for(const other of document.querySelectorAll('[data-book-side]')){const active=other===button;other.classList.toggle('active',active);other.setAttribute('aria-pressed',String(active));}renderBook();});
function clock(){text('utc-clock',timeOnly(Date.now())+' UTC');}clock();setInterval(clock,1000);
render();
loadSnapshot().then(detectService).then(discover);
setInterval(discover,180000);setInterval(refreshTracked,20000);
setInterval(()=>{renderPaper();if(state.book)renderBook();},15000);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')refreshTracked();});
