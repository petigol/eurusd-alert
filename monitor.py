#!/usr/bin/env python3
"""TradingKey EUR/USD alert monitor. Public pages only; fail closed."""
import os, re, json, sys, time, hashlib, urllib.robotparser
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

BASE='https://www.tradingkey.com'
TOPIC=os.getenv('NTFY_TOPIC','').strip()
SERVER=os.getenv('NTFY_SERVER','https://ntfy.sh').rstrip('/')
STATE=Path('state.json')
UA='EURUSD-Research-Alert/1.0 (public pages; respectful fetch)'
S=requests.Session();S.headers.update({'User-Agent':UA,'Accept-Language':'en-US,en;q=0.9'})

def fetch(url):
    r=S.get(url,timeout=20)
    if r.status_code in (403,429):raise RuntimeError('TradingKey access restricted: '+str(r.status_code))
    r.raise_for_status();return r.text

def latest():
    robots=urllib.robotparser.RobotFileParser();robots.set_url(BASE+'/robots.txt');robots.read()
    pages=[]
    for n in (1,2):
        url=f'{BASE}/tools/trading?page={n}'
        if not robots.can_fetch(UA,url):raise RuntimeError('robots.txt disallows archive')
        soup=BeautifulSoup(fetch(url),'html.parser')
        pages.extend(urljoin(BASE,a.get('href','')) for a in soup.select('a[href*="/tools/trading/"]'))
        time.sleep(1.5)
    links=list(dict.fromkeys(x for x in pages if re.fullmatch(r'https://www\.tradingkey\.com/tools/trading/\d+',x)))
    # IDs are normally increasing, but do not assume page order is always correct.
    links.sort(key=lambda x:int(x.rsplit('/',1)[-1]),reverse=True)
    for url in links[:35]:
        if not robots.can_fetch(UA,url):raise RuntimeError('robots.txt disallows article')
        soup=BeautifulSoup(fetch(url),'html.parser');title=soup.title.get_text(' ',strip=True) if soup.title else ''
        text=soup.get_text(' ',strip=True)
        if not re.search(r'EUR\s*/\s*USD',title,re.I) or not re.search(r'intraday',title,re.I):
            time.sleep(1.5);continue
        pm=re.search(r'Our pivot point is at\s+(\d+\.\d+)',text,re.I)
        tm=re.search(r'with\s+(\d+\.\d+)\s+and\s+(\d+\.\d+)\s+as targets',text,re.I)
        dm=re.search(r'the\s+(upside|downside)\s+prevails',text,re.I)
        dt=re.search(r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+20\d{2}\s+\d{1,2}:\d{2}\s*(?:AM|PM)',text,re.I)
        if not all((pm,tm,dm,dt)):
            print('Skipping incomplete article:',url);time.sleep(1.5);continue
        direction='LONG' if dm.group(1).lower()=='upside' else 'SHORT'
        pivot,t1,t2=map(float,(pm.group(1),tm.group(1),tm.group(2)))
        if not (1.0<pivot<1.4 and 1.0<t1<1.4 and 1.0<t2<1.4):continue
        if not (t1>pivot if direction=='LONG' else t1<pivot):continue
        # Publication timestamp on TradingKey is displayed without a verified timezone.
        # Do not infer age from it: mark freshness unknown, and suppress price-zone alert.
        return dict(url=url,direction=direction,pivot=pivot,target1=t1,target2=t2,published=dt.group(0),publication_timezone_verified=False)
    return None

def quote():
    # Yahoo chart is a fallback public data source, not a broker execution quote.
    url='https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1m&range=1d'
    r=S.get(url,timeout=15);r.raise_for_status();d=r.json()['chart']['result'][0]
    timestamps=d.get('timestamp') or []
    closes=d['indicators']['quote'][0]['close']
    pairs=[(t,p) for t,p in zip(timestamps,closes) if p is not None]
    if not pairs:raise RuntimeError('No EURUSD quotes')
    ts,price=pairs[-1]
    stamp=datetime.fromtimestamp(ts,timezone.utc)
    if datetime.now(timezone.utc)-stamp>timedelta(minutes=15):raise RuntimeError('Stale EURUSD quote')
    return float(price),stamp.isoformat(),url

def notify(title,message,tags='chart_with_upwards_trend'):
    if not TOPIC:raise RuntimeError('NTFY_TOPIC missing')
    if not re.fullmatch(r'[A-Za-z0-9_-]{3,100}',TOPIC):raise RuntimeError('Invalid topic')
    if not SERVER.startswith('https://'):raise RuntimeError('HTTPS ntfy server required')
    r=requests.post(f'{SERVER}/{TOPIC}',data=message.encode('utf-8'),headers={'Title':title,'Tags':tags,'Priority':'default'},timeout=15)
    r.raise_for_status()

def main():
    state=json.loads(STATE.read_text()) if STATE.exists() else {}
    signal=latest()
    if not signal:print('No verified EUR/USD intraday signal found; no notification');return
    key=hashlib.sha256(json.dumps([signal[k] for k in ('direction','pivot','target1','target2')]).encode()).hexdigest()[:16]
    print('Signal:',signal)
    if key!=state.get('signal_key'):
        notify('EUR/USD Trading Central: '+signal['direction'],f"{signal['direction']} | pivot {signal['pivot']:.4f} | TP1 {signal['target1']:.4f} | TP2 {signal['target2']:.4f}\nTradingKey kijelzett idő: {signal['published']} (időzóna nem igazolt)\n{signal['url']}\nÚj szintkombináció; manuális ellenőrzés szükséges.")
        state['signal_key']=key;state['last_signal']=signal
    # SAFETY: No price-based alerts until publication timezone/freshness is independently verified.
    # A 2:1 signal on a stale recommendation is misleading, so intentionally suppress it.
    print('Price-zone alert disabled: TradingKey publication timezone not independently verified.')
    STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':
    try:main()
    except Exception as e:print('Monitor failed safely:',repr(e),file=sys.stderr);sys.exit(1)
