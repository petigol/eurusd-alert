import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
from bs4 import BeautifulSoup
import monitor as m

class MonitorTests(unittest.TestCase):
 def test_publication_matches_article(self):
  soup=BeautifulSoup('<script>window.__QUDE_LOADER_DATA__={"x":[{"details":{"id":"42","symbol":"EURUSD","period":"INTRADAY","publishAt":"1793637900"}}]}</script>','html.parser')
  self.assertEqual(m.publication_time(soup,'42').isoformat(),'2026-11-02T16:45:00+00:00')
  self.assertIsNone(m.publication_time(soup,'43'))
 def test_duplicate_and_unknown_publication(self):
  with tempfile.TemporaryDirectory() as d:
   signal=dict(url='https://www.tradingkey.com/tools/trading/42',direction='LONG',pivot=1.1,target1=1.11,target2=1.12,published='Nov 2, 2026 4:45 PM',publication_timezone_verified=False,published_utc=None)
   with patch.object(m,'STATE',Path(d)/'state.json'),patch.object(m,'latest',return_value=signal),patch.object(m,'quote',return_value=(1.101,datetime.now(timezone.utc).isoformat(),'test')),patch.object(m,'notify') as notify:
    m.main();m.main();self.assertEqual(notify.call_count,1)
    signal['publication_timezone_verified']=True;signal['published_utc']=datetime.now(timezone.utc).isoformat()
    m.main();m.main();self.assertEqual(notify.call_count,2)
    signal['url']='https://www.tradingkey.com/tools/trading/43'
    m.main();self.assertEqual(notify.call_count,4)
 def test_quote_rejects_stale_future_and_nonfinite(self):
  for delta,price in [(timedelta(minutes=-6),1.1),(timedelta(minutes=2),1.1),(timedelta(),float('nan'))]:
   data={'chart':{'result':[{'timestamp':[(datetime.now(timezone.utc)+delta).timestamp()],'indicators':{'quote':[{'close':[price]}]}}]}}
   with patch.object(m.S,'get') as get:
    get.return_value.json.return_value=data
    with self.assertRaises(RuntimeError):m.quote()
class DirectionChangeTests(unittest.TestCase):
 def test_transitions_duplicates_and_stale_articles(self):
  now=datetime.now(timezone.utc)
  def signal(direction,minute):
   return dict(url='https://www.tradingkey.com/tools/trading/'+str(minute),direction=direction,
    pivot=1.1,target1=1.11,target2=1.12,publication_timezone_verified=True,
    published_utc=(now+timedelta(minutes=minute)).isoformat())
  state={}
  with patch.object(m,'notify') as notify,patch.object(m,'save'):
   m.check_direction_change(state,signal('LONG',-4))
   m.check_direction_change(state,signal('LONG',-3))
   self.assertEqual(notify.call_count,0)
   m.check_direction_change(state,signal('SHORT',-2))
   m.check_direction_change(state,signal('SHORT',-2))
   self.assertEqual(notify.call_count,1)
   m.check_direction_change(state,signal('LONG',-4))
   self.assertEqual(state['direction_baseline']['direction'],'SHORT')
   unknown=signal('LONG',-1);unknown['publication_timezone_verified']=False
   m.check_direction_change(state,unknown)
   self.assertEqual(notify.call_count,1)
   m.check_direction_change(state,signal('LONG',-1))
   self.assertEqual(notify.call_count,2)
 def test_failed_delivery_retries_without_advancing_baseline(self):
  now=datetime.now(timezone.utc).isoformat()
  previous=dict(url='old',direction='LONG',published_utc=now)
  current=dict(url='new',direction='SHORT',published_utc=now,publication_timezone_verified=True,
   pivot=1.1,target1=1.09,target2=1.08)
  state={'direction_baseline':previous}
  with patch.object(m,'save'),patch.object(m,'notify',side_effect=RuntimeError('delivery failed')):
   with self.assertRaises(RuntimeError):m.check_direction_change(state,current)
  self.assertEqual(state['direction_baseline'],previous)

if __name__=='__main__':unittest.main()
