import json
import unittest

from radar import config
from radar.fast_live_scanner import FastLiveRadarScanner


class FakeDB:
    def __init__(self,last=None,meta=None):
        self.meta=dict(meta or {})
        if last is not None:self.meta['last_block']=str(last)
    def get_meta(self,key,default=None):return self.meta.get(key,default)
    def set_meta(self,key,value):self.meta[key]=str(value)
    def last_block(self):
        value=self.meta.get('last_block');return int(value) if value is not None else None


class FakeRPC:
    def __init__(self,tip,timestamps=None):self.tip=tip;self.timestamps=dict(timestamps or {})
    def block_number(self):return self.tip
    def block(self,n):return {'hash':'0x'+format(int(n),'064x'),'timestamp':hex(int(self.timestamps.get(int(n),0)))}


def scanner(last,tip,meta=None,timestamps=None):
    s=FastLiveRadarScanner.__new__(FastLiveRadarScanner)
    s.db=FakeDB(last,meta)
    s.rpc=FakeRPC(tip,timestamps=timestamps)
    s.diag=[];s._block_time={}
    s._stage=lambda *args,**kwargs:None
    return s


class RuntimeRecoveryTests(unittest.TestCase):
    def test_large_outage_rebases_to_live_lookback_and_records_gap(self):
        tip=50000
        s=scanner(100,tip)
        s._runtime_rebase_if_stale()
        safe=tip-config.CONFIRMATION_BLOCKS
        expected_first=max(0,safe-config.INITIAL_LOOKBACK_BLOCKS+1)
        expected_checkpoint=expected_first-1
        self.assertEqual(s.db.last_block(),expected_checkpoint)
        self.assertEqual(s.db.get_meta('last_block_hash'),'0x'+format(expected_checkpoint,'064x'))
        gaps=json.loads(s.db.get_meta('historical_gaps_json'))
        self.assertEqual(gaps,[[101,expected_checkpoint]])
        self.assertTrue(any(d.get('reason')=='RUNTIME_CURSOR_REBASED' for d in s.diag))

    def test_realistic_13k_block_backlog_rebases_before_watchdog_loop(self):
        tip=50000
        safe=tip-config.CONFIRMATION_BLOCKS
        last=safe-13326
        s=scanner(last,tip)
        s._runtime_rebase_if_stale()
        expected_first=max(0,safe-config.INITIAL_LOOKBACK_BLOCKS+1)
        expected_checkpoint=expected_first-1
        self.assertEqual(s.db.last_block(),expected_checkpoint)
        gaps=json.loads(s.db.get_meta('historical_gaps_json'))
        self.assertEqual(gaps,[[last+1,expected_checkpoint]])

    def test_chain_time_stale_rebases_even_inside_block_cap(self):
        tip=50000
        safe=tip-config.CONFIRMATION_BLOCKS
        last=safe-500
        timestamps={last:1000,safe:1000+config.RUNTIME_REBASE_LAG_SECONDS+1}
        s=scanner(last,tip,{'last_block_hash':'0xold'},timestamps=timestamps)
        s._runtime_rebase_if_stale()
        expected_first=max(0,safe-config.INITIAL_LOOKBACK_BLOCKS+1)
        expected_checkpoint=expected_first-1
        self.assertEqual(s.db.last_block(),expected_checkpoint)
        gaps=json.loads(s.db.get_meta('historical_gaps_json'))
        self.assertEqual(gaps,[[last+1,expected_checkpoint]])

    def test_small_lag_keeps_durable_cursor(self):
        tip=50000
        safe=tip-config.CONFIRMATION_BLOCKS
        last=safe-min(2000,max(1,config.RUNTIME_REBASE_LAG_BLOCKS//2))
        timestamps={last:1000,safe:1000+min(30,config.RUNTIME_REBASE_LAG_SECONDS)}
        s=scanner(last,tip,{'last_block_hash':'0xold'},timestamps=timestamps)
        s._runtime_rebase_if_stale()
        self.assertEqual(s.db.last_block(),last)
        self.assertEqual(s.db.get_meta('last_block_hash'),'0xold')
        self.assertIsNone(s.db.get_meta('historical_gaps_json'))

    def test_disjoint_historical_gaps_are_not_falsely_merged(self):
        s=scanner(100,100,{'historical_gap_from':'10','historical_gap_to':'20'})
        s._record_historical_gap(30,40)
        s._record_historical_gap(41,45)
        self.assertEqual(json.loads(s.db.get_meta('historical_gaps_json')),[[10,20],[30,45]])

    def test_explicit_public_lookback_never_rebases_persistent_cursor(self):
        s=scanner(100,50000,{'last_block_hash':'0xold'})
        s._runtime_rebase_if_stale(public_lookback=3)
        self.assertEqual(s.db.last_block(),100)
        self.assertEqual(s.db.get_meta('last_block_hash'),'0xold')
        self.assertIsNone(s.db.get_meta('historical_gaps_json'))


if __name__=='__main__':unittest.main()
