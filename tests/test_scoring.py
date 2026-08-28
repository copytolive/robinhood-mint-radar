import unittest
from radar.scoring import compute_metrics, score_candidate

class ScoreTests(unittest.TestCase):
    def test_free_fast_safe_candidate_scores_high_but_market_gate_is_real(self):
        now=10000
        events=[{'block_time':now-10,'quantity':1,'recipient':f'0x{i:040x}'} for i in range(20)]
        m=compute_metrics(events,now)
        score=score_candidate(0,m,{'total_supply':900,'max_supply':1000},{'state':'PASS','verified':True},{'state':'LIVE','sales_24h':30,'volume_24h':5000})
        self.assertGreaterEqual(score['score'],85)
        self.assertTrue(score['qualified'])

    def test_missing_market_fails_closed(self):
        now=10000
        events=[{'block_time':now-5,'quantity':1,'recipient':f'0x{i:040x}'} for i in range(50)]
        m=compute_metrics(events,now)
        score=score_candidate(0,m,{'total_supply':990,'max_supply':1000},{'state':'PASS','verified':True},{'state':'UNAVAILABLE'})
        self.assertFalse(score['qualified'])
        self.assertIn('MARKET_EVIDENCE_UNAVAILABLE',score['hard_gates'])

if __name__=='__main__': unittest.main()
