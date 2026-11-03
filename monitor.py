#!/usr/bin/env python3
"""TradingKey EUR/USD alert monitor. Public pages only; fail closed."""
import os, re, json, sys, time, hashlib, math, urllib.robotparser
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

def publication_time(soup, article_id):
    """Read the publication epoch from this exact EURUSD article, never first-seen."""
    for node in soup.select('script'):
        text=node.string or node.get_text()
        marker='window.__QUDE_LOADER_DATA__='
        if marker not in text: continue
        try:
            data,_=json.JSONDecoder().raw_decode(text.split(marker,1)[1])
        except ValueError: continue
        def walk(obj):
            if isinstance(obj,dict):
                if (str(obj.get('id'))==article_id and obj.get('symbol')=='EURUSD'
                        and obj.get('period')=='INTRADAY' and str(obj.get('publishAt','')).isdigit()):
                    yield datetime.fromtimestamp(int(obj['publishAt']),timezone.utc)
                for value in obj.values(): yield from walk(value)
            elif isinstance(obj,list):
                for value in obj: yield from walk(value)
        stamps=list(walk(data))
        if stamps and len(set(stamps))==1: return stamps[0]
    return None

def latest():
    robots=urllib.robotparser.RobotFileParser();robots.parse(fetch(BASE+'/robots.txt').splitlines())
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
        if not (pivot<t1<t2 if direction=='LONG' else t2<t1<pivot):continue
        # Publication timestamp on TradingKey is displayed without a verified timezone.
        # Do not infer age from it: mark freshness unknown, and suppress price-zone alert.
        published_utc=publication_time(soup,url.rsplit('/',1)[-1])
        return dict(url=url,direction=direction,pivot=pivot,target1=t1,target2=t2,
                    published=dt.group(0),publication_timezone_verified=published_utc is not None,
                    published_utc=published_utc.isoformat() if published_utc else None)
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
    age=datetime.now(timezone.utc)-stamp
    if not timedelta(seconds=-60)<=age<=timedelta(minutes=5):raise RuntimeError('Stale/future EURUSD quote: '+str(age))
    if not math.isfinite(float(price)) or float(price)<=0:raise RuntimeError('Invalid EURUSD quote')
    return float(price),stamp.isoformat(),url

def notify(title,message,tags='chart_with_upwards_trend'):
    if not TOPIC:raise RuntimeError('NTFY_TOPIC missing')
    if not re.fullmatch(r'[A-Za-z0-9_-]{3,100}',TOPIC):raise RuntimeError('Invalid topic')
    if not SERVER.startswith('https://'):raise RuntimeError('HTTPS ntfy server required')
    r=requests.post(f'{SERVER}/{TOPIC}',data=message.encode('utf-8'),headers={'Title':title,'Tags':tags,'Priority':'default'},timeout=15)
    if not r.ok:raise RuntimeError('ntfy delivery failed HTTP '+str(r.status_code))
    print('ntfy accepted notification:',title)

def save(state):
    tmp=STATE.with_suffix('.tmp');tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');tmp.replace(STATE)


def check_direction_change(state, signal):
    """Alert once per chronological, source-dated primary-direction transition."""
    if not signal.get('publication_timezone_verified') or not signal.get('published_utc'):
        return
    stamp=datetime.fromisoformat(signal['published_utc'])
    age=datetime.now(timezone.utc)-stamp
    if not timedelta(minutes=-5)<=age<=timedelta(hours=24):
        return
    previous=state.get('direction_baseline') or state.get('last_signal',{})
    old_direction=previous.get('direction')
    old_stamp=previous.get('published_utc')
    if old_stamp and stamp<datetime.fromisoformat(old_stamp):
        print('Direction check: older article ignored')
        return
    if old_direction in ('LONG','SHORT') and old_direction!=signal['direction'] and old_stamp:
        event=hashlib.sha256(json.dumps([previous.get('url'),old_direction,
            signal['url'],signal['direction'],signal['published_utc']]).encode()).hexdigest()[:24]
        delivered=state.setdefault('direction_change_alerts',[])
        if event not in delivered:
            notify('EUR/USD IRANYVALTAS: '+old_direction+' -> '+signal['direction'],
                   f"Az eredeti forgatókönyv megváltozott – ellenőrizd a pozíciót.\n"
                   f"Trading Central: {old_direction} → {signal['direction']}\n"
                   f"Új pivot: {signal['pivot']:.4f} | TP1: {signal['target1']:.4f} | TP2: {signal['target2']:.4f}\n"
                   f"Forrás publikáció UTC: {signal['published_utc']}\n{signal['url']}\n"
                   "Ez irányváltási figyelmeztetés, nem automatikus zárás. A program nem ismeri a tényleges pozíciódat.",
                   tags='warning')
            delivered.append(event)
    state['direction_baseline']=dict(signal)
    save(state)

def main():
    state=json.loads(STATE.read_text()) if STATE.exists() else {}
    signal=latest()
    if not signal:
        print('No verified EUR/USD intraday signal found; no notification')
        return
    key=hashlib.sha256(json.dumps([signal[k] for k in ('url','direction','pivot','target1','target2')]).encode()).hexdigest()[:24]
    print('Signal:',signal)
    seen=state.setdefault('seen_forecasts',[])
    zones=state.setdefault('zone_alerts',[])
    # Migrate the already delivered legacy signal without sending it again.
    old=state.get('last_signal',{})
    if not seen and all(old.get(k)==signal[k] for k in ('url','direction','pivot','target1','target2')):
        seen.append(key)
        if state.get('zone_alerted_key'): zones.append(key)
    state.setdefault('first_seen_by_forecast',{}).setdefault(key,datetime.now(timezone.utc).isoformat())
    check_direction_change(state,signal)
    # Probe the quote on every run, even when publication age is unknown.
    quote_data=None
    try:
        quote_data=quote()
        print('Quote:',quote_data)
    except (requests.RequestException,ValueError,KeyError,IndexError,TypeError,RuntimeError) as exc:
        print('Quote unavailable:',type(exc).__name__)
    if key not in seen:
        notify('EUR/USD Trading Central: '+signal['direction'],
               f"{signal['direction']} | pivot {signal['pivot']:.4f} | TP1 {signal['target1']:.4f} | TP2 {signal['target2']:.4f}\n"
               f"Forrás publikáció UTC: {signal['published_utc'] or 'nem igazolt'}\n"
               f"TradingKey kijelzett idő: {signal['published']}\n{signal['url']}")
        seen.append(key)
    state['last_signal']=signal
    save(state)
    # No price-zone alerts on timestamps lacking a timezone-aware source.
    if not signal['publication_timezone_verified']:
        print('Price-zone alert disabled: no timezone-aware publication metadata.')
    else:
        pub=datetime.fromisoformat(signal['published_utc'])
        age=datetime.now(timezone.utc)-pub
        if not timedelta(minutes=-5)<=age<=timedelta(hours=24):
            print('Price-zone alert disabled: publication outside 24h freshness window:',age)
        else:
            try:
                if quote_data is None:raise RuntimeError('No fresh quote')
                price,quote_time,quote_source=quote_data
                pivot=signal['pivot']; target=signal['target1']
                if signal['direction']=='LONG':
                    inside=pivot<price<target
                    risk=(price-pivot)*10000
                    reward=(target-price)*10000
                else:
                    inside=target<price<pivot
                    risk=(pivot-price)*10000
                    reward=(price-target)*10000
                rr=reward/risk if inside and risk>0 else 0
                qualifies=inside and rr>=2.0 and risk>=3.0
                print(f'Quote={price:.5f} at {quote_time}; risk={risk:.1f}p; reward={reward:.1f}p; RR={rr:.2f}; qualifies={qualifies}')
                # One alert per distinct signal level combination. Reset only on new combination.
                if qualifies and key not in zones:
                    notify('EUR/USD BELÉPÉSI ZÓNA: '+signal['direction'],
                           f"{signal['direction']} | ár {price:.5f} | pivot {pivot:.4f} | TP1 {target:.4f}\n"
                           f"Stop-távolság {risk:.1f} pip | céltávolság {reward:.1f} pip | R/R {rr:.2f}:1\n"
                           f"Árfolyam UTC: {quote_time}\nElemzés UTC: {signal['published_utc']}\n"
                           f"Trading Central: {signal['url']}\nÁrfolyamforrás: {quote_source}\n"
                           'Tájékoztató jelzés; a pivot feltételezett stop, a spread és a csúszás módosíthatja az R/R-t.',
                           tags='dart')
                    zones.append(key)
                    save(state)
            except (requests.RequestException,ValueError,KeyError,RuntimeError) as exc:
                print('Price-zone check unavailable; no zone alert:',type(exc).__name__)
    save(state)

if __name__=='__main__':
    try:main()
    except Exception as e:print('Monitor failed safely:',type(e).__name__,file=sys.stderr);sys.exit(1)

