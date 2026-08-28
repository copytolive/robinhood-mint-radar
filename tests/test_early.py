import unittest
from radar.scoring import score_candidate

class EarlyQualificationTests(unittest.TestCase):
    def test_verified_free_hoodsea_can_qualify_without_opensea_key(self):
        metrics={'velocity_1m':20,'velocity_5m':5,'acceleration_5m':3,'unique_recent_minters':40,'recent_mint_concentration':0.05}
        out=score_candidate(0,metrics,{'total_supply':500,'max_supply':1000},{'state':'PASS','verified':True},{'state':'EARLY_ONCHAIN_ONLY'},relevance={'state':'PASS'},is_hoodsea=True,launch=True)
        self.assertTrue(out['qualified'])
        self.assertEqual(out['qualification_path'],'EARLY_ONCHAIN_ONLY')
    def test_early_non_hoodsea_stays_blocked(self):
        metrics={'velocity_1m':20,'velocity_5m':5,'acceleration_5m':3,'unique_recent_minters':40,'recent_mint_concentration':0.05}
        out=score_candidate(0,metrics,{'total_supply':500,'max_supply':1000},{'state':'PASS','verified':True},{'state':'EARLY_ONCHAIN_ONLY'},relevance={'state':'PASS'},is_hoodsea=False,launch=False)
        self.assertFalse(out['qualified'])
