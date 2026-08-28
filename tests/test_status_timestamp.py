import unittest
from unittest.mock import patch
from radar.cli import finalize_status


class StatusTimestampTests(unittest.TestCase):
    def test_generated_at_is_completion_time(self):
        status={
            'generated_at':100,
            'live_ready':'READY',
            'money_readiness':'WAIT FOR QUALIFIED OPPORTUNITY',
            'status':'SCANNING 900-950',
            'chain':{'safe_block':1000},
            'scan':{'from_block':900,'to_block':1000,'qualified_candidates':0},
            'watchlist':[],
            'best_live_observation':None,
            'manual_packages':[],
            'diagnostics':[],
        }
        with patch('radar.cli.time.time',return_value=1000.9):
            out=finalize_status(status)
        self.assertIs(out,status)
        self.assertEqual(out['generated_at'],1000)
        self.assertEqual(out['live_ready'],'READY')
        self.assertEqual(out['scan']['lag_blocks'],0)
        self.assertEqual(out['status'],'SCANNING 900-1000')
