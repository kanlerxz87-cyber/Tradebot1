import {BASE, DOCS, TOPICS, topicFor, price, qty, dollars, count, marketUrl, eventUrl, bookUrl, sample, qualifies, swing, resolution, estimate, paperBuy, paperPnl} from './core.mjs';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const now = () => new Date().toLocaleTimeString('en-US', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
const fmtTime = value => value ? new Date(value).toLocaleString('en-US', {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '—';
const state = { events:new Map(), markets:new Map(), history:new Map(), alerts:[], selected:null, source:'Waiting for data', updated:null, partial:true, paper:[], candles:[], candleLabel:'Session samples', loading:false, seen:new Map(), watch:new Set(), cycle:0, topic:document.body.dataset.topic || 'all' };
try { const saved=JSON.parse(localStorage.getItem('kalshi-paper-v1') || '[]'); if(Array.isArray(saved)) state.paper=saved.filter(t=>t && typeof t.ticker==='string' && typeof t.entry==='number').slice(-250); } catch {} // storage is optional
function save() { try { localStorage.setItem('kalshi-paper-v1', JSON.stringify(state.paper)); } catch {} }
function fetchJson(url, ms=14000) { return fetch(url, {cache:'no-store', signal:AbortSignal.timeout(ms)}).then(r=>{if(!r.ok) throw Error(`HTTP ${r.status}`);return r.json();}); }
function record(m, event, origin='REST') {
  if(!m?.ticker || !event || !topicFor(event)) return;
  const previous=state.markets.get(m.ticker), seen=state.seen.get(m.ticker), prev=previous && sample(previous), next=sample(m);
  state.seen.set(m.ticker,{at:Date.now(),origin,cycle:state.cycle});
  state.markets.set(m.ticker, m); state.events.set(event.event_ticker,event);
  if(next !== null) {
    const history=state.history.get(m.ticker) || [];
    if(!history.length || history.at(-1).v !== next) {
      history.push({t:Date.now(),v:next}); state.history.set(m.ticker,history.slice(-1000));
    }
  }
  // A first observation is a baseline, not a swing. Market prices may skip intrapoll moves.
  const change=origin!=='snapshot' && seen && seen.origin!=='snapshot' && seen.cycle!==state.cycle && Date.now()-seen.at<180000 && previous.status==='active' && m.status==='active' ? swing(prev,next) : null;
  if(change !== null) {
    state.alerts.unshift({ticker:m.ticker,eventTicker:m.event_ticker,topic:topicFor(event),title:m.title || event.title,change,price:next,at:Date.now(),screen:qualifies(m),origin});
    state.alerts=state.alerts.slice(0,120);
    if(qualifies(m) && !state.paper.some(t=>t.ticker===m.ticker)) {
      const trade=paperBuy(m,topicFor(event),'Spread / activity screen');
      if(trade) { state.paper.push(trade); save(); }
    }
  }
  if(resolution(m) && state.paper.some(t=>t.ticker===m.ticker && !t.result)) {
    state.paper.forEach(t=>{if(t.ticker===m.ticker) t.result=resolution(m);}); save();
  }
}
function allRows() {
  return [...state.markets.values()].filter(m=>{ const e=state.events.get(m.event_ticker); return e && (state.topic==='all'||topicFor(e)===state.topic); });
}
function topRows() { const rows=allRows().filter(m=>m.status==='active');const totals=new Map();for(const m of rows)totals.set(m.event_ticker,(totals.get(m.event_ticker)||0)+(estimate(m)||0));return rows.sort((a,b)=>(totals.get(b.event_ticker)-totals.get(a.event_ticker))||((estimate(b)??-1)-(estimate(a)??-1))).slice(0,80); }
function setStatus(message, type='') { $('connection').textContent=message; $('connection').className='status '+type; }
function stats() {
  const rows=topRows(); $('stat-events').textContent=new Set(rows.map(m=>m.event_ticker)).size.toLocaleString();
  $('stat-markets').textContent=rows.length.toLocaleString();
  $('stat-alerts').textContent=state.alerts.filter(a=>a.topic===state.topic || state.topic==='all').length;
  $('stat-updated').textContent=state.updated ? fmtTime(state.updated) : '—';
  $('coverage').textContent=`${state.source} · ${state.partial?'Sampled coverage; not a complete exchange ranking':'Complete scanned pages'} · ${state.updated?fmtTime(state.updated):'no confirmed timestamp'}`;
}
function table() {
  const rows=topRows();
  $('market-rows').innerHTML=rows.length ? rows.map(m=>{
    const e=state.events.get(m.event_ticker), topic=topicFor(e), est=estimate(m), selected=m.ticker===state.selected;
    return `<tr class="${selected?'selected':''}"><td><span class="topic-tag ${topic}">${esc(topic)}</span><button class="market-link" data-select="${esc(m.ticker)}">${esc(e.title)}</button><small>${esc(m.title || m.ticker)} · ${esc(m.ticker)}</small></td><td class="num">${dollars(sample(m))}</td><td class="num">${dollars(price(m.yes_bid_dollars))} / ${dollars(price(m.yes_ask_dollars))}</td><td class="num">${count(qty(m.volume_24h_fp))}</td><td class="num">${est===null?'—':dollars(est)}</td><td>${esc(m.status)}${resolution(m)?' · '+resolution(m):''}</td><td><a href="${marketUrl(m.ticker)}" target="_blank" rel="noopener noreferrer" aria-label="Kalshi source for ${esc(m.ticker)}">API ↗</a></td></tr>`;
  }).join('') : '<tr><td colspan="7" class="empty">No matching verified market rows available. A blank is not a zero. Check connection and coverage.</td></tr>';
  document.querySelectorAll('[data-select]').forEach(button=>button.addEventListener('click',()=>select(button.dataset.select)));
}
function feeds() {
  const list=state.alerts.filter(a=>state.topic==='all'||a.topic===state.topic);
  for(const [id,items] of [['all-feed',list],['screen-feed',list.filter(a=>a.screen)]]) {
    $(id).innerHTML=items.length?items.slice(0,45).map(a=>`<article class="feed-item"><div class="feed-top"><span class="${a.change>0?'up':'down'}">${a.change>0?'↗ +':'↘ −'}${Math.abs(a.change).toFixed(2)}</span><time>${fmtTime(a.at)}</time></div><strong>${esc(a.title)}</strong><small>${esc(a.topic)} · last price ${dollars(a.price)} · ${esc(a.origin)} observation</small><a href="${marketUrl(a.ticker)}" target="_blank" rel="noopener noreferrer">Market source ↗</a><small>Cause: unverified — no article linked to this move</small></article>`).join(''):'<p class="empty">Waiting for an observed ±$0.10 change. No retrospective alerts are invented.</p>';
  }
}
function paper() {
  let realized=0, open=0;
  const lines=state.paper.filter(t=>state.topic==='all'||t.topic===state.topic).slice().reverse();
  $('paper-rows').innerHTML=lines.length?lines.slice(0,60).map(t=>{
    const m=state.markets.get(t.ticker), pnl=m?paperPnl(t,m):t.result?((t.result==='YES'?1:0)-t.entry):null;
    if(pnl!==null) {if(t.result) realized+=pnl; else open+=pnl;}
    return `<tr><td>${esc(t.topic)}<small>${esc(t.strategy)}</small></td><td>${esc(t.ticker)}<small>${fmtTime(t.at)}</small></td><td class="num">${dollars(t.entry)}</td><td>${esc(t.result||'Open / unknown')}</td><td class="num ${pnl===null?'':pnl>=0?'up':'down'}">${pnl===null?'—':(pnl>=0?'+':'')+dollars(pnl)}</td><td><a href="${marketUrl(t.ticker)}" target="_blank" rel="noopener noreferrer">API ↗</a></td></tr>`;
  }).join(''):'<tr><td colspan="6" class="empty">No paper trades. The screen starts after an observed swing; it never submits real orders.</td></tr>';
  $('paper-summary').textContent=`${lines.length} simulated YES buys · marked P&L ${dollars(realized+open)} across quoted rows only · excludes fees & slippage`;
}
function plot(points, label) {
  const svg=$('chart'); svg.replaceChildren();
  const S='http://www.w3.org/2000/svg'; const add=(tag,attrs,text)=>{const el=document.createElementNS(S,tag);Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,v));if(text!==undefined)el.textContent=text;svg.appendChild(el);return el;};
  add('rect',{x:0,y:0,width:700,height:250,fill:'transparent'});
  for(let i=0;i<=4;i++){const y=20+i*49;add('line',{x1:50,y1:y,x2:680,y2:y,stroke:'#263d50','stroke-dasharray':'3 5'});add('text',{x:8,y:y+4,fill:'#8ea7b1','font-size':'11'},'$'+(1-i*.25).toFixed(2));}
  if(!points.length){add('text',{x:190,y:130,fill:'#8ea7b1','font-size':'14'},'No confirmed price samples for this range');$('chart-caption').textContent=label;return;}
  const min=points[0].t,max=points.at(-1).t,span=Math.max(1,max-min);
  const coords=points.map(p=>[50+(p.t-min)/span*630,216-p.v*196]);
  if(coords.length>1)add('polyline',{points:coords.map(p=>p.join(',')).join(' '),fill:'none',stroke:'#35dbab','stroke-width':'2.5','stroke-linejoin':'round'});
  coords.slice(-80).forEach(p=>add('circle',{cx:p[0],cy:p[1],r:2.5,fill:'#35dbab'}));
  add('text',{x:50,y:244,fill:'#8ea7b1','font-size':'11'},fmtTime(min));add('text',{x:580,y:244,fill:'#8ea7b1','font-size':'11'},fmtTime(max));
  $('chart-caption').textContent=label+' · x: observation time · y: YES last traded price ($)';
}
function chart() {
  const mode=$('range').value, cutoff=Date.now()-({seconds:300000,minutes:3600000,hours:86400000}[mode]);
  const session=(state.history.get(state.selected)||[]).filter(p=>p.t>=cutoff);
  const candles=mode==='seconds'?[]:state.candles.filter(p=>p.t>=cutoff);
  plot(candles.length?candles:session,candles.length?state.candleLabel:'Browser-session samples (not exchange history)');
}
async function loadCandles(ticker) {
  state.candles=[];state.candleLabel='Browser-session samples';chart();
  const event=state.events.get(state.markets.get(ticker)?.event_ticker);
  if(!event?.series_ticker)return;
  const period=$('range').value==='hours'?60:1;
  const end=Math.floor(Date.now()/1000), start=end-(period===60?86400:3600);
  const url=`${BASE}/series/${encodeURIComponent(event.series_ticker)}/markets/${encodeURIComponent(ticker)}/candlesticks?start_ts=${start}&end_ts=${end}&period_interval=${period}`;
  try {const data=await fetchJson(url);if(state.selected!==ticker)return;
    state.candles=(data.candlesticks||[]).map(c=>({t:c.end_period_ts*1000,v:price(c.price?.close_dollars)})).filter(p=>p.v!==null).sort((a,b)=>a.t-b.t);
    state.candleLabel=`Kalshi ${period===60?'hourly':'minute'} candlestick close (may lag)`;chart();
  } catch { $('chart-caption').textContent+=' · Candles unavailable'; }
}
async function select(ticker) {
  state.selected=ticker;const m=state.markets.get(ticker), e=state.events.get(m?.event_ticker);if(!m||!e)return;
  $('detail-title').textContent=e.title; $('detail-sub').textContent=`${m.title||m.ticker} · ${m.ticker}`;
  $('detail-source').href=marketUrl(ticker);$('event-source').href=eventUrl(e.event_ticker);
  $('detail-meta').textContent=`YES last ${dollars(sample(m))}  ·  Bid ${dollars(price(m.yes_bid_dollars))}  ·  Ask ${dollars(price(m.yes_ask_dollars))}  ·  ${resolution(m)||m.status}`;
  $('rule-text').textContent=m.rules_primary||'Rules not supplied in this market response; consult the event source.';
  const sources=(e.settlement_sources||[]).filter(x=>{try{return new URL(x.url).protocol==='https:'}catch{return false}}).slice(0,3);
  $('settlement-sources').replaceChildren();for(const s of sources){const a=document.createElement('a');a.href=s.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=(s.name||'Settlement source')+' ↗';$('settlement-sources').append(a);}
  $('book-rows').innerHTML='<tr><td colspan="3" class="empty">Loading public orderbook…</td></tr>';
  table();chart();loadCandles(ticker);
  try {const data=await fetchJson(bookUrl(ticker));if(state.selected!==ticker)return;
    const book=data.orderbook_fp||{}, bids=[...(book.yes_dollars||[])].reverse().slice(0,5), no=[...(book.no_dollars||[])].reverse().slice(0,5);
    $('book-rows').innerHTML=Array.from({length:Math.max(bids.length,no.length)},(_,i)=>`<tr><td class="num">${bids[i]?dollars(price(bids[i][0])):'—'} / ${bids[i]?count(qty(bids[i][1])):'—'}</td><td class="num">${no[i]?dollars(price(no[i][0])):'—'} / ${no[i]?count(qty(no[i][1])):'—'}</td><td><a href="${bookUrl(ticker)}" target="_blank" rel="noopener noreferrer">API ↗</a></td></tr>`).join('')||'<tr><td colspan="3" class="empty">No resting bids reported. Not a quote to buy.</td></tr>';
  } catch {if(state.selected===ticker)$('book-rows').innerHTML='<tr><td colspan="3" class="empty">Orderbook unavailable; no levels inferred.</td></tr>';}
}
function lifecycle() {
  const rows=[...state.markets.values()].filter(m=>m.status!=='active' && state.watch.has(m.ticker) && (state.topic==='all'||topicFor(state.events.get(m.event_ticker))===state.topic)).slice(-80);
  $('resolution-rows').innerHTML=rows.length?rows.map(m=>`<tr><td>${esc(state.events.get(m.event_ticker)?.title||m.event_ticker)}<small>${esc(m.ticker)}</small></td><td>${esc(m.status)}</td><td>${resolution(m)||'—'}</td><td><a href="${marketUrl(m.ticker)}" target="_blank" rel="noopener noreferrer">API ↗</a></td></tr>`).join(''):'<tr><td colspan="4" class="empty">No watched contracts have closed yet. A determination is not final settlement.</td></tr>';
}
function render() {stats();table();feeds();paper();lifecycle();if(state.selected){const m=state.markets.get(state.selected);if(m){$('detail-meta').textContent=`YES last ${dollars(sample(m))} · Bid ${dollars(price(m.yes_bid_dollars))} · Ask ${dollars(price(m.yes_ask_dollars))} · ${resolution(m)||m.status}`;chart();}}}
async function refreshWatch() {
  if(state.loading)return;state.cycle++;
  const tickers=[...new Set([...state.watch,...topRows().map(m=>m.ticker),...state.paper.map(t=>t.ticker),state.selected].filter(Boolean))].slice(-100);
  if(!tickers.length)return;
  for(let i=0;i<tickers.length;i+=20){
    try {const data=await fetchJson(`${BASE}/markets?tickers=${tickers.slice(i,i+20).map(encodeURIComponent).join(',')}`);
      for(const m of data.markets||[]){const event=state.events.get(m.event_ticker);if(event)record(m,event,'tracked REST');}
    } catch {} // status retains last successful observation
  }
  render();
}
async function liveRefresh() {
  if(state.loading)return;state.loading=true;state.cycle++;setStatus('Refreshing demo REST…','pending');
  try {
    let cursor='',pages=0,items=[],marketCursor='',marketPages=0,newest=[];
    // Events lists include long-dated markets. Supplement them with newest non-combo markets.
    do {const q=new URLSearchParams({limit:'200',status:'open',with_nested_markets:'true'});if(cursor)q.set('cursor',cursor);
      const data=await fetchJson(`${BASE}/events?${q}`);items.push(...(data.events||[]));cursor=data.cursor||'';pages++;
    } while(cursor && pages<4);
    for(const event of items)if(topicFor(event))for(const market of event.markets||[])record(market,event);
    do {const q=new URLSearchParams({limit:'1000',status:'open',mve_filter:'exclude'});if(marketCursor)q.set('cursor',marketCursor);
      const data=await fetchJson(`${BASE}/markets?${q}`);newest.push(...(data.markets||[]));marketCursor=data.cursor||'';marketPages++;
    } while(marketCursor && marketPages<2);
    const candidates=newest.filter(m=>m.event_ticker).sort((a,b)=>(estimate(b)??-1)-(estimate(a)??-1)).slice(0,400);
    const tickers=[...new Set(candidates.map(m=>m.event_ticker))];const matched=new Map();
    for(let i=0;i<tickers.length;i+=50){const data=await fetchJson(`${BASE}/events?tickers=${tickers.slice(i,i+50).map(encodeURIComponent).join(',')}`);
      for(const event of data.events||[])if(topicFor(event))matched.set(event.event_ticker,event);
    }
    for(const market of candidates){const event=matched.get(market.event_ticker);if(event)record(market,event);}
    if(!items.length && !newest.length)throw Error('No public markets returned');
    state.source=`Demo REST · ${items.length} event rows + ${newest.length} newest non-combo markets scanned`;
    state.partial=!!cursor||!!marketCursor||candidates.length<newest.length;for(const m of topRows())state.watch.add(m.ticker);if(state.watch.size>100)state.watch=new Set([...state.watch].slice(-100));state.updated=new Date().toISOString();setStatus('Demo REST connected','ok');
    if(!state.selected && topRows().length)await select(topRows()[0].ticker);
    render();
  } catch(error) {setStatus('REST unavailable · '+error.message,'error');$('coverage').textContent=`${state.source} · ${state.updated?`last observed ${fmtTime(state.updated)}`:'no live observations'} · fetch failed (CORS/network/rate limit possible)`;}
  finally {state.loading=false;}
}
async function snapshot() {
  try {const data=await fetchJson(new URL('../data/snapshot.json',import.meta.url));
    for(const event of data.events||[])if(topicFor(event))for(const market of event.markets||[])record(market,event,'snapshot');
    if(data.generated_at){state.source='Published API snapshot';state.updated=data.generated_at;state.partial=!!data.partial;setStatus('Snapshot · checking live REST','pending');}
    for(const m of topRows())state.watch.add(m.ticker);if(!state.selected&&topRows().length)select(topRows()[0].ticker);render();
  } catch {render();}
}
$('range').addEventListener('change',()=>{chart();if(state.selected)loadCandles(state.selected);});
$('refresh').addEventListener('click',liveRefresh);
snapshot().finally(()=>{liveRefresh();setInterval(liveRefresh,90000);setInterval(refreshWatch,45000);});
