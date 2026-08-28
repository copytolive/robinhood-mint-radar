import unittest
from radar.cli import finalize_status
from radar import config


class LiveLagTests(unittest.TestCase):
    def test_backlog_forces_not_ready_and_blocks_package(self):
        candidate={'qualified':True,'qualification_path':'MARKET_CONFIRMED','action':'MANUAL_MINT_CANDIDATE','hard_gates':[]}
        status={
            'live_ready':'READY',
            'money_readiness':'QUALIFIED OPPORTUNITY AVAILABLE',
            'chain':{'safe_block':20000},
            'scan':{'to_block':10000,'qualified_candidates':1},
            'watchlist':[dict(candidate)],
            'best_live_observation':dict(candidate),
            'manual_packages':[dict(candidate)],
            'diagnostics':[],
        }
        out=finalize_status(status)
        self.assertEqual(out['live_ready'],'NOT_READY')
        self.assertEqual(out['scan']['lag_blocks'],10000)
        self.assertEqual(out['scan']['qualified_candidates'],0)
        self.assertEqual(out['manual_packages'],[])
        self.assertIn('SCANNER_NOT_CAUGHT_UP',out['watchlist'][0]['hard_gates'])
        self.assertEqual(out['watchlist'][0]['action'],'WAIT')
        self.assertTrue(any(d.get('reason')=='SCANNER_BACKLOG' for d in out['diagnostics']))

    def test_near_tip_can_remain_ready(self):
        status={
            'live_ready':'READY',
            'money_readiness':'WAIT FOR QUALIFIED OPPORTUNITY',
            'chain':{'safe_block':20000},
            'scan':{'to_block':20000,'qualified_candidates':0},
            'watchlist':[],
            'best_live_observation':None,
            'manual_packages':[],
            'diagnostics':[],
        }
        out=finalize_status(status)
        self.assertEqual(out['live_ready'],'READY')
        self.assertEqual(out['scan']['lag_blocks'],0)

    def test_high_throughput_chunk_is_not_legacy_60(self):
        self.assertGreaterEqual(config.CHUNK_BLOCKS,1000)
        self.assertGreaterEqual(config.MAX_CATCHUP_BLOCKS,config.CHUNK_BLOCKS)


if __name__=='__main__':
    unittest.main()
