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
if __name__=='__main__':unittest.main()
