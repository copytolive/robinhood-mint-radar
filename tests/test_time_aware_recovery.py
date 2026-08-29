import json
import unittest

from radar import config
from radar.time_aware_live_scanner import TimeAwareLiveRadarScanner


class FakeDB:
    def __init__(self,last,meta=None):
        self.meta=dict(meta or {})
        self.meta['last_block']=str(last)
    def get_meta(self,key,default=None):return self.meta.get(key,default)
    def set_meta(self,key,value):self.meta[key]=str(value)
    def last_block(self):return int(self.meta['last_block'])


class FakeRPC:
    def __init__(self,tip):self.tip=tip
    def block_number(self):return self.tip
    def block(self,n):
        # Simulate the observed high-throughput chain cadence: ~10 blocks/sec.
        return {'hash':'0x'+format(int(n),'064x'),'timestamp':hex(int(n)//10)}


def scanner(last,tip,meta=None):
    s=TimeAwareLiveRadarScanner.__new__(TimeAwareLiveRadarScanner)
    s.db=FakeDB(last,meta)
    s.rpc=FakeRPC(tip)
    s.diag=[]
    s._block_time={}
    s._stage=lambda *args,**kwargs:None
    return s


class TimeAwareRecoveryTests(unittest.TestCase):
    def test_sub_2k_backlog_rebases_when_chain_time_exceeds_readiness(self):
        tip=50000
        safe=tip-config.CONFIRMATION_BLOCKS
        last=safe-1363
        self.assertLess(1363,config.MAX_READY_LAG_BLOCKS)
        s=scanner(last,tip)
        s._runtime_rebase_if_stale()
        expected_first=max(0,safe-config.INITIAL_LOOKBACK_BLOCKS+1)
        expected_checkpoint=expected_first-1
        self.assertEqual(s.db.last_block(),expected_checkpoint)
        self.assertEqual(json.loads(s.db.get_meta('historical_gaps_json')),[[last+1,expected_checkpoint]])
        self.assertTrue(any(d.get('reason')=='RUNTIME_CURSOR_REBASED' for d in s.diag))

    def test_fresh_subminute_cursor_is_not_rebased(self):
        tip=50000
        safe=tip-config.CONFIRMATION_BLOCKS
        last=safe-400
        s=scanner(last,tip,{'last_block_hash':'0xold'})
        s._runtime_rebase_if_stale()
        self.assertEqual(s.db.last_block(),last)
        self.assertEqual(s.db.get_meta('last_block_hash'),'0xold')
        self.assertIsNone(s.db.get_meta('historical_gaps_json'))

    def test_public_lookback_never_rebases(self):
        s=scanner(100,50000,{'last_block_hash':'0xold'})
        s._runtime_rebase_if_stale(public_lookback=3)
        self.assertEqual(s.db.last_block(),100)
        self.assertIsNone(s.db.get_meta('historical_gaps_json'))


if __name__=='__main__':unittest.main()
