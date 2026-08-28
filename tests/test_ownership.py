import unittest
from unittest.mock import patch
from radar.explorer import BlockscoutClient

class OwnershipTests(unittest.TestCase):
    def test_top_holder_share(self):
        c=BlockscoutClient('https://x/api')
        with patch.object(c,'_get_json',side_effect=[{'items':[{'value':'4'},{'value':'2'}],'next_page_params':None},{'token_holders_count':'6'}]):
            out=c.ownership('0x'+'1'*40,total_supply=10)
        self.assertEqual(out['state'],'LIVE'); self.assertEqual(out['top_holder_share'],0.4)
