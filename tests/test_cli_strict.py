import unittest
from unittest.mock import patch
from radar import cli


def _status(lag_seconds=0, live_ready='READY'):
    return {
        'mode':'READ_ONLY',
        'wallet_execution':'MANUAL_ONLY',
        'live_ready':live_ready,
        'money_readiness':'WAIT FOR QUALIFIED OPPORTUNITY',
        'chain':{'chain_id':4663,'latest_block':110,'safe_block':100},
        'scan':{'to_block':100,'lag_seconds':lag_seconds,'analysis_age_seconds':1,'qualified_candidates':0},
        'watchlist':[],
        'best_live_observation':None,
        'manual_packages':[],
        'diagnostics':[],
    }


class _Scanner:
    def __init__(self,results):
        self.results=list(results);self.calls=0;self.closed=False;self.db=object()
    def scan_once(self,public_lookback=None):
        self.calls+=1
        result=self.results.pop(0)
        if isinstance(result,Exception):raise result
        return result
    def close(self):self.closed=True


class StrictCLITests(unittest.TestCase):
    def test_strict_once_retries_not_ready_with_warm_scanner(self):
        scanner=_Scanner([_status(120,'NOT_READY'),_status(61,'NOT_READY'),_status(0,'READY')])
        with patch('radar.cli.RadarScanner',return_value=scanner),patch('radar.cli.write_status'),patch('radar.cli.notify_qualified',return_value={'state':'NO_QUALIFIED_PACKAGE'}),patch('radar.cli.time.sleep') as sleep:
            rc=cli.main(['--once','--strict','--db','/tmp/test.sqlite','--status','/tmp/status.json'])
        self.assertEqual(rc,0)
        self.assertEqual(scanner.calls,3)
        self.assertEqual(sleep.call_count,2)

    def test_strict_once_fails_after_three_not_ready_results(self):
        scanner=_Scanner([_status(120,'NOT_READY'),_status(120,'NOT_READY'),_status(120,'NOT_READY')])
        with patch('radar.cli.RadarScanner',return_value=scanner),patch('radar.cli.write_status'),patch('radar.cli.notify_qualified',return_value={'state':'NO_QUALIFIED_PACKAGE'}),patch('radar.cli.time.sleep'):
            rc=cli.main(['--once','--strict'])
        self.assertEqual(rc,2)
        self.assertEqual(scanner.calls,3)

    def test_strict_once_recreates_scanner_after_transient_exception(self):
        first=_Scanner([ConnectionResetError(54,'reset')]);second=_Scanner([_status(0,'READY')]);created=[]
        def factory(_db):
            obj=first if not created else second
            created.append(obj)
            return obj
        with patch('radar.cli.RadarScanner',side_effect=factory),patch('radar.cli.write_status'),patch('radar.cli.notify_qualified',return_value={'state':'NO_QUALIFIED_PACKAGE'}),patch('radar.cli.time.sleep'):
            rc=cli.main(['--once','--strict'])
        self.assertEqual(rc,0)
        self.assertTrue(first.closed)
        self.assertEqual(second.calls,1)


if __name__=='__main__':unittest.main()
