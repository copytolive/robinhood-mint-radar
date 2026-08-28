import unittest
from unittest.mock import patch
from radar.notify import notify_qualified

class FakeDB:
    def __init__(self):self.x={}
    def get_meta(self,k):return self.x.get(k)
    def set_meta(self,k,v):self.x[k]=v

class NotifyTests(unittest.TestCase):
    def test_no_package_is_noop(self):
        self.assertEqual(notify_qualified({'manual_packages':[]})['state'],'NO_QUALIFIED_PACKAGE')
    @patch('radar.notify.platform.system',return_value='Darwin')
    @patch('radar.notify.subprocess.run')
    def test_dedupes(self,run,system):
        db=FakeDB();s={'manual_packages':[{'collection':'0xabc','name':'X','score':90,'mint_price_eth':0,'qualification_path':'MARKET_CONFIRMED'}]}
        self.assertEqual(notify_qualified(s,db)['state'],'SENT')
        self.assertEqual(notify_qualified(s,db)['state'],'DEDUPED')
        self.assertEqual(run.call_count,1)
