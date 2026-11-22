"""Bounded public-only demo API snapshot for GitHub Pages; never reads secrets.

Does not claim comprehensive coverage. Failure retains an explicit empty/unavailable
snapshot rather than manufacturing market values.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = 'https://external-api.demo.kalshi.co/trade-api/v2'
OUT = Path('docs/data/snapshot.json')
PATTERNS = [r'\b(gasoline|gas prices?|gallon of gas|pump prices?)\b',
            r'\b(bitcoin|ethereum|ether|crypto|dogecoin|solana|btc|eth)\b',
            r'\b(golf|pga|masters|ryder cup|us open golf|open championship)\b',
            r'\b(grammy|oscar|emmy|movie|film|music|album|artist|celebrity|box office|tv show|television|tiktok|youtube)\b']
ELECTION = r'\b(elect\w*|vot\w*|ballot|presiden\w*|senat\w*|governor\w*|mayor\w*|congress\w*|primary|party)\b'
FIELDS = ('ticker','event_ticker','title','status','result','last_price_dollars','yes_bid_dollars',
          'yes_ask_dollars','yes_bid_size_fp','yes_ask_size_fp','volume_24h_fp','volume_fp',
          'close_time','rules_primary')
def matches(e):
    title = str(e.get('title') or '').lower()
    return any(re.search(p,title) for p in PATTERNS) or (e.get('category','').lower()=='elections' and re.search(ELECTION,title))
def fetch(path, params):
    url = BASE+path+'?'+urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={'User-Agent':'Tradebot1-public-research/1.0'})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)
def add_event(events, e, markets):
    if not matches(e) or not markets: return
    ticker=e.get('event_ticker')
    if not ticker:return
    if ticker not in events:
        events[ticker]={key:e[key] for key in ('event_ticker','series_ticker','title','category','settlement_sources') if key in e} | {'markets':[]}
    known={m['ticker'] for m in events[ticker]['markets']}
    events[ticker]['markets'].extend({key:m[key] for key in FIELDS if key in m} for m in markets if m.get('ticker') and m['ticker'] not in known)

def main():
    event_cursor='';market_cursor='';event_pages=0;market_pages=0;events={};error=None
    try:
        while event_pages<4:
            params={'limit':200,'status':'open','with_nested_markets':'true'}
            if event_cursor:params['cursor']=event_cursor
            data=fetch('/events',params);event_pages+=1
            for e in data.get('events',[]):add_event(events,e,e.get('markets',[]))
            event_cursor=data.get('cursor') or ''
            if not event_cursor:break
            time.sleep(.25)
        newest=[]
        while market_pages<2:
            params={'limit':1000,'status':'open','mve_filter':'exclude'}
            if market_cursor:params['cursor']=market_cursor
            data=fetch('/markets',params);market_pages+=1
            newest.extend(data.get('markets',[]))
            market_cursor=data.get('cursor') or ''
            if not market_cursor:break
            time.sleep(.25)
        def activity(m):
            try:return float(m.get('last_price_dollars') or 0)*float(m.get('volume_24h_fp') or 0)
            except (ValueError,TypeError):return 0
        candidates=sorted(newest,key=activity,reverse=True)[:400]
        ids=list(dict.fromkeys(m.get('event_ticker') for m in candidates if m.get('event_ticker')))
        market_by_event={}
        for m in candidates:market_by_event.setdefault(m.get('event_ticker'),[]).append(m)
        for i in range(0,len(ids),50):
            data=fetch('/events',{'tickers':','.join(ids[i:i+50])})
            for e in data.get('events',[]):add_event(events,e,market_by_event.get(e.get('event_ticker'),[]))
            time.sleep(.25)
    except (OSError,ValueError,KeyError) as exc:
        error=str(exc)[:200]
    result={'generated_at':datetime.now(timezone.utc).isoformat() if event_pages and not error else None,
            'partial':bool(event_cursor or market_cursor or error), 'scanned_event_pages':event_pages,
            'scanned_market_pages':market_pages,'error':error,
            'events':list(events.values()) if not error else []}
    OUT.write_text(json.dumps(result,separators=(',',':'))+'\n')
    print('Snapshot:',event_pages,'event pages,',market_pages,'market pages,',len(result['events']),'matching events, partial:',result['partial'],'error:',error)
if __name__=='__main__': main()
