import unittest
from unittest.mock import patch
from radar.explorer import BlockscoutClient

class OwnershipTests(unittest.TestCase):
    def test_top_holder_share(self):
        c=BlockscoutClient('https://x/api')
        with patch.object(c,'_get_json',side_effect=[{'items':[{'value':'4'},{'value':'2'}],'next_page_params':None},{'token_holders_count':'6'}]):
            out=c.ownership('0x'+'1'*40,total_supply=10)
        self.assertEqual(out['state'],'LIVE'); self.assertEqual(out['top_holder_share'],0.4)
        self.assertEqual(out['holders_count'],6); self.assertEqual(out['holders_count_state'],'LIVE')

    def test_inconsistent_counter_is_not_published_as_fact(self):
        c=BlockscoutClient('https://x/api')
        items=[{'value':'1'} for _ in range(50)]
        with patch.object(c,'_get_json',side_effect=[{'items':items,'next_page_params':{'value':'1'}},{'token_holders_count':'1'}]):
            out=c.ownership('0x'+'2'*40,total_supply=1000)
        self.assertEqual(out['state'],'LIVE')
        self.assertIsNone(out['holders_count'])
        self.assertEqual(out['holders_count_state'],'INCONSISTENT')
        self.assertEqual(out['holders_count_lower_bound'],50)
        self.assertEqual(out['sampled_holders'],50)
        self.assertEqual(out['top_holder_share'],0.001)

if __name__=='__main__': unittest.main()
