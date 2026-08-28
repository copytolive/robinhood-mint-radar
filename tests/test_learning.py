import os,tempfile,unittest
from radar.db import RadarDB

class LearningTests(unittest.TestCase):
    def test_outcome_and_shadow(self):
        with tempfile.TemporaryDirectory() as td:
            db=RadarDB(os.path.join(td,'radar.sqlite'))
            net=db.record_outcome('0xabc','MINT',10,18,0.5,'p1')
            self.assertAlmostEqual(net,7.5)
            stats=db.outcome_stats()
            self.assertEqual(stats['samples'],1)
            self.assertAlmostEqual(stats['realized_net_usd'], 7.5)
            self.assertIn('net_capital_day_pct', stats)
            db.observe_shadow({'collection':'0xabc','score':88,'action':'WATCH','market':{'floor_price':1.0}},100)
            db.observe_shadow({'collection':'0xabc','score':90,'action':'WATCH','market':{'floor_price':2.5}},200)
            sh=db.shadow_stats()
            self.assertEqual(sh['tracked'],1)
            self.assertEqual(sh['reached_2x'],1)
            db.close()

if __name__=='__main__': unittest.main()
