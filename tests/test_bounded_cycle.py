import unittest
from unittest.mock import patch

from radar import config
from radar.bounded_fast_live_scanner import BoundedFastLiveRadarScanner


class FakeDB:
    def __init__(self,last):
        self.meta={'last_block':str(last),'last_block_hash':'0xold'}
    def last_block(self):return int(self.meta['last_block'])
    def get_meta(self,key,default=None):return self.meta.get(key,default)
    def set_meta(self,key,value):self.meta[key]=str(value)
    def total_mints(self):return 0
    def total_market_sales(self):return 0
    def total_launches(self):return 0
    def db_health(self):return {'integrity':'ok'}


class MovingRPC:
    def __init__(self,tips):
        self.tips=list(tips);self.i=0;self.url='https://rpc.mainnet.chain.robinhood.com';self.failovers=0
    def chain_id(self):return config.CHAIN_ID
    def block_number(self):
        value=self.tips[min(self.i,len(self.tips)-1)];self.i+=1;return value
    def block(self,n):return {'hash':'0x'+format(int(n),'064x')}


class Harness(BoundedFastLiveRadarScanner):
    def __init__(self,last,tips,lag_seconds=0):
        self.db=FakeDB(last);self.rpc=MovingRPC(tips);self.diag=[];self.max_ingest_range_blocks=128
        self._analysis_rows_cache=[];self._analysis_pruned=0;self._analysis_overflow=0;self.ranges=[];self.test_lag_seconds=lag_seconds
    def _runtime_rebase_if_stale(self,public_lookback=None):return None
    def _verify_checkpoint(self,last,stored_hash):return last
    def _init_signatures(self):return None
    def _stage(self,*args,**kwargs):return None
    def _scan_range_or_raise(self,a,b):self.ranges.append((a,b));return 0
    def _checkpoint(self,n):self.db.set_meta('last_block',n);self.db.set_meta('last_block_hash','0x'+format(n,'064x'))
    def _prepare_analysis_rows(self):self._analysis_rows_cache=[];return []
    def _prewarm_enrichment(self):return None
    def build_status(self,tip,safe,first,processed_to,started):
        return {'chain':{},'scan':{},'diagnostics':[],'live_ready':'READY','money_readiness':'WAIT FOR QUALIFIED OPPORTUNITY','manual_packages':[],'watchlist':[],'best_live_observation':None}
    def _lag_metrics(self,safe,processed):return max(0,safe-processed),self.test_lag_seconds
    def block_time(self,n):return 0


class BoundedCycleTests(unittest.TestCase):
    def test_cycle_does_not_chase_a_moving_safe_tip(self):
        # Initial tip=1000 => fixed safe target=990. Final tip jumps to 2000.
        s=Harness(last=800,tips=[1000,2000])
        status=s.scan_once()
        self.assertEqual(s.ranges,[(801,928),(929,990)])
        self.assertEqual(status['scan']['to_block'],990)
        self.assertEqual(status['scan']['next_block'],991)
        self.assertEqual(status['chain']['latest_block'],2000)

    def test_wall_clock_budget_exits_normally_when_chain_time_is_stale(self):
        s=Harness(last=100,tips=[1000,1100],lag_seconds=120)
        old=config.INGEST_CYCLE_BUDGET_SECONDS
        config.INGEST_CYCLE_BUDGET_SECONDS=5
        values=iter([0,10])
        def fake_time():
            try:return next(values)
            except StopIteration:return 11
        try:
            with patch('radar.bounded_fast_live_scanner.time.time',side_effect=fake_time):
                status=s.scan_once()
        finally:
            config.INGEST_CYCLE_BUDGET_SECONDS=old
        self.assertEqual(s.ranges,[(101,228)])
        self.assertEqual(status['live_ready'],'NOT_READY')
        self.assertEqual(status['money_readiness'],'CATCHING UP — WAIT FOR LIVE TIP')
        self.assertEqual(status['scan']['next_block'],229)
        self.assertEqual(status['scan']['lag_seconds'],120)
        self.assertTrue(any(d.get('reason')=='INGEST_BUDGET_EXHAUSTED' for d in status['diagnostics']))

    def test_wall_clock_budget_continues_to_analysis_inside_ready_window(self):
        s=Harness(last=100,tips=[1000,1100,1100],lag_seconds=30)
        old=config.INGEST_CYCLE_BUDGET_SECONDS
        config.INGEST_CYCLE_BUDGET_SECONDS=5
        values=iter([0,10])
        def fake_time():
            try:return next(values)
            except StopIteration:return 11
        try:
            with patch('radar.bounded_fast_live_scanner.time.time',side_effect=fake_time):
                status=s.scan_once()
        finally:
            config.INGEST_CYCLE_BUDGET_SECONDS=old
        self.assertEqual(s.ranges,[(101,228)])
        self.assertEqual(status['live_ready'],'READY')
        self.assertEqual(status['scan']['next_block'],229)
        self.assertEqual(status['scan']['lag_seconds'],30)


if __name__=='__main__':unittest.main()
