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
            'scan':{'to_block':10000,'lag_seconds':600,'analysis_age_seconds':1,'qualified_candidates':1},
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

    def test_stale_analysis_blocks_package_even_when_cursor_is_live(self):
        candidate={'qualified':True,'qualification_path':'MARKET_CONFIRMED','action':'MANUAL_MINT_CANDIDATE','hard_gates':[]}
        status={
            'live_ready':'READY',
            'money_readiness':'QUALIFIED OPPORTUNITY AVAILABLE',
            'chain':{'safe_block':20000},
            'scan':{'to_block':20000,'lag_seconds':0,'analysis_age_seconds':config.MAX_READY_LAG_SECONDS+1,'qualified_candidates':1},
            'watchlist':[dict(candidate)],
            'best_live_observation':dict(candidate),
            'manual_packages':[dict(candidate)],
            'diagnostics':[],
        }
        out=finalize_status(status)
        self.assertEqual(out['live_ready'],'NOT_READY')
        self.assertEqual(out['money_readiness'],'ANALYSIS REFRESHING — WAIT')
        self.assertEqual(out['manual_packages'],[])
        self.assertIn('ANALYSIS_TOO_OLD',out['watchlist'][0]['hard_gates'])
        self.assertTrue(any(d.get('reason')=='ANALYSIS_STALE' for d in out['diagnostics']))

    def test_near_tip_can_remain_ready(self):
        status={
            'live_ready':'READY',
            'money_readiness':'WAIT FOR QUALIFIED OPPORTUNITY',
            'chain':{'safe_block':20000},
            'scan':{'to_block':20000,'lag_seconds':0,'analysis_age_seconds':1,'qualified_candidates':0},
            'watchlist':[],
            'best_live_observation':None,
            'manual_packages':[],
            'diagnostics':[],
        }
        out=finalize_status(status)
        self.assertEqual(out['live_ready'],'READY')
        self.assertEqual(out['scan']['lag_blocks'],0)

    def test_fast_chain_146_blocks_is_ready_when_only_seconds_behind(self):
        status={
            'live_ready':'READY',
            'money_readiness':'WAIT FOR QUALIFIED OPPORTUNITY',
            'chain':{'safe_block':48340242},
            'scan':{'to_block':48340096,'lag_seconds':14,'analysis_age_seconds':1,'qualified_candidates':0},
            'watchlist':[],
            'best_live_observation':None,
            'manual_packages':[],
            'diagnostics':[],
        }
        out=finalize_status(status)
        self.assertEqual(out['scan']['lag_blocks'],146)
        self.assertEqual(out['scan']['lag_seconds'],14)
        self.assertEqual(out['live_ready'],'READY')

    def test_high_throughput_chunk_is_not_legacy_60(self):
        self.assertGreaterEqual(config.CHUNK_BLOCKS,1000)
        self.assertGreaterEqual(config.MAX_CATCHUP_BLOCKS,config.CHUNK_BLOCKS)
        self.assertGreaterEqual(config.MAX_READY_LAG_BLOCKS,1000)
        self.assertLessEqual(config.MAX_READY_LAG_SECONDS,120)


if __name__=='__main__':
    unittest.main()
