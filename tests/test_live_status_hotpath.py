import unittest
from unittest.mock import patch

from radar.bounded_fast_live_scanner import BoundedFastLiveRadarScanner
from radar.fast_live_scanner import FastLiveRadarScanner


class FakeConn:
    def execute(self,sql):
        class Row:
            def fetchone(self_inner):
                return (1,) if sql == 'SELECT 1' else ('wal',)
        return Row()


class FakeDB:
    def __init__(self):
        self.conn=FakeConn()
        self.path='/tmp/fake.sqlite'
        self.integrity_check=lambda:(_ for _ in ()).throw(AssertionError('full integrity must not run'))
        self.db_health=lambda:(_ for _ in ()).throw(AssertionError('full db_health must not run'))
        self.total_mints=lambda:(_ for _ in ()).throw(AssertionError('full mint sum must not run'))
        self.total_market_sales=lambda:(_ for _ in ()).throw(AssertionError('full market count must not run'))
        self.total_launches=lambda:(_ for _ in ()).throw(AssertionError('full launch count must not run'))


class LiveStatusHotPathTests(unittest.TestCase):
    def test_bounded_status_replaces_heavy_db_calls_and_restores_them(self):
        s=object.__new__(BoundedFastLiveRadarScanner)
        s.db=FakeDB()
        s._maybe_maintain=lambda _now:(_ for _ in ()).throw(AssertionError('maintenance must not run'))
        s._stage=lambda *a,**k:None
        s._previous_scan_counters=lambda:{
            'total_mint_units_stored':123,
            'secondary_sales_stored':45,
            'hoodsea_launches_stored':6,
        }
        original_integrity=s.db.integrity_check
        original_health=s.db.db_health
        original_mints=s.db.total_mints

        def fake_parent(scanner,*args,**kwargs):
            scanner._maybe_maintain(0)
            self.assertEqual(scanner.db.integrity_check(),'ok')
            self.assertEqual(scanner.db.total_mints(),123)
            self.assertEqual(scanner.db.total_market_sales(),45)
            self.assertEqual(scanner.db.total_launches(),6)
            health=scanner.db.db_health()
            self.assertEqual(health['integrity'],'RUNTIME_OPERATIONAL')
            return {'live_ready':'READY','money_readiness':'WAIT FOR QUALIFIED OPPORTUNITY','manual_packages':[],'scan':{},'watchlist':[],'diagnostics':[],'db':health}

        with patch.object(FastLiveRadarScanner,'build_status',new=fake_parent):
            status=s.build_status(100,90,80,90,0)

        self.assertEqual(status['live_ready'],'READY')
        self.assertEqual(status['scan']['heavy_db_metrics_state'],'DEFERRED_TO_DOCTOR_OR_MAINTENANCE')
        self.assertIs(s.db.integrity_check,original_integrity)
        self.assertIs(s.db.db_health,original_health)
        self.assertIs(s.db.total_mints,original_mints)


if __name__=='__main__':
    unittest.main()
