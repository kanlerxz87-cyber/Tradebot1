// Browser-only research simulation. Never calls an account endpoint or creates an exchange order.
import {price,qty,resolution,marketUrl,topicFor} from './core.mjs';
const SCALE=1_000_000;
export const STRATEGIES=['momentum','mean_reversion'];
export function emptyPaper() {
  return {version:2,mode:'hypothetical_browser_ledger',startingCash:1000,
    accounts:Object.fromEntries(STRATEGIES.map(name=>[name,{cashMicros:1000*SCALE,positions:[]}]))};
}
export function restorePaper(value) {
  if(value?.version!==2||value?.mode!=='hypothetical_browser_ledger')return emptyPaper();
  for(const name of STRATEGIES) {
    const account=value.accounts?.[name];
    if(!account||!Number.isSafeInteger(account.cashMicros)||account.cashMicros<0||!Array.isArray(account.positions))return emptyPaper();
    if(account.positions.some(p=>!p?.ticker||!p.eventTicker||!['yes','no'].includes(p.side)||!Number.isSafeInteger(p.costMicros)||p.costMicros<=0||p.costMicros>=SCALE||!['open','settled'].includes(p.status)))return emptyPaper();
  }
  return value;
}
export function simulateAlert(state,alert,market,event,now=Date.now()) {
  if(market.status!=='active'||price(market.notional_value_dollars)!==1||!market.event_ticker)return false;
  if(market.settlement_bounds_type && market.settlement_bounds_type!=='default')return false;
  const age=now-(market._meta?.observedAt||0);
  if(market._meta?.kind!=='rest'||age<0||age>10000)return false;
  const bid=price(market.yes_bid_dollars),ask=price(market.yes_ask_dollars);
  if(bid===null||ask===null||ask<=bid||Math.round((ask-bid)*SCALE)>40000)return false;
  let changed=false;
  for(const strategy of STRATEGIES) {
    const account=state.accounts[strategy];
    if(account.positions.some(position=>position.ticker===market.ticker))continue;
    const followSide=alert.change>0?'yes':'no';
    const side=strategy==='momentum'?followSide:(followSide==='yes'?'no':'yes');
    const quote=side==='yes'?ask:price(market.no_ask_dollars);
    const size=side==='yes'?qty(market.yes_ask_size_fp):qty(market.yes_bid_size_fp);
    if(quote===null||quote<=0||quote>=1||size===null||size<1)continue;
    const costMicros=Math.round(quote*SCALE);
    const eventCost=account.positions.filter(p=>p.eventTicker===market.event_ticker&&p.status==='open').reduce((sum,p)=>sum+p.costMicros,0);
    if(account.cashMicros<costMicros||eventCost+costMicros>20*SCALE)continue;
    account.cashMicros-=costMicros;
    account.positions.push({id:`${strategy}:${market.ticker}:${alert.at}`,ticker:market.ticker,eventTicker:market.event_ticker,
      topic:topicFor(event),strategy,side,count:1,entry:quote,costMicros,at:alert.at,status:'open',result:null,
      grossPnl:null,fees:null,source_url:market.source_url||marketUrl(market.ticker),
      assumption:'Hypothetical fill at reported ask and displayed size; no exchange execution or queue guarantee'});
    changed=true;
  }
  return changed;
}
export function settlePaper(state,market) {
  const result=resolution(market)?.toLowerCase();
  if(!result||price(market.notional_value_dollars)!==1)return false;
  if(market.settlement_bounds_type && market.settlement_bounds_type!=='default')return false;
  const settlement=price(market.settlement_value_dollars);
  if(settlement!==null&&settlement!==(result==='yes'?1:0))return false;
  let changed=false;
  for(const account of Object.values(state.accounts))for(const position of account.positions) {
    if(position.ticker!==market.ticker||position.status!=='open')continue;
    const payout=position.side===result?SCALE:0;
    position.status='settled';position.result=result;position.grossPnl=(payout-position.costMicros)/SCALE;
    position.settlementSource=market.source_url||marketUrl(market.ticker);account.cashMicros+=payout;changed=true;
  }
  return changed;
}
export function paperSummary(state,markets,now=Date.now()) {
  const accounts={};
  for(const [name,account] of Object.entries(state.accounts)) {
    let mark=0,complete=true,realized=0;
    const rows=account.positions.map(position=>{
      if(position.status==='settled'){realized+=position.grossPnl;return position;}
      const market=markets.get(position.ticker);
      const bid=price(market?.[`${position.side}_bid_dollars`]);
      const age=now-(market?._meta?.observedAt||0);
      const usable=bid!==null&&age>=0&&age<=45000&&market?._meta?.kind!=='snapshot';
      if(!usable)complete=false;else mark+=bid;
      return {...position,grossPnl:usable?(Math.round(bid*SCALE)-position.costMicros)/SCALE:null};
    });
    accounts[name]={cash:account.cashMicros/SCALE,positions:rows,realizedGross:realized,
      grossEquity:complete?account.cashMicros/SCALE+mark:null,netRoi:null,fees:null};
  }
  return {mode:state.mode,startingCash:state.startingCash,accounts};
}
