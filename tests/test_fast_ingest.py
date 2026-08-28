import unittest

from radar import config
from radar.fast_live_scanner import FastLiveRadarScanner
from radar.rpc import RPCError


def _word_address(ch='1'):
    return '0x'+('0'*24)+(ch*40)


class _DB:
    def __init__(self):
        self.mints=[];self.launches=[];self.sales=[]
    def add_mint(self,row):self.mints.append(row)
    def add_launch(self,row):self.launches.append(row)
    def add_market_sale(self,row):self.sales.append(row)


class _IngestRPC:
    def __init__(self,block_ok=True):
        self.block_ok=block_ok;self.batch_calls=[];self.block_calls=[]
        self.log={
            'blockNumber':'0x65',
            'logIndex':'0x1',
            'transactionHash':'0xtx',
            'address':'0x'+'a'*40,
            'topics':[config.TRANSFER_TOPIC,config.ZERO_TOPIC,_word_address('1'),'0x'+('0'*63)+'7'],
            'data':'0x',
        }
    def batch_call(self,calls):
        self.batch_calls.append(calls)
        return [[self.log],[],[],[],[],[]]
    def blocks(self,numbers,batch_size=64,max_workers=16):
        self.block_calls.append(list(numbers))
        return {int(n):({'timestamp':'0x64'} if self.block_ok else None) for n in numbers}


class FastIngestTests(unittest.TestCase):
    def _scanner(self,block_ok=True):
        s=FastLiveRadarScanner.__new__(FastLiveRadarScanner)
        s.db=_DB();s.ingest_rpc=_IngestRPC(block_ok);s._block_time={};s.diag=[]
        s._topics={
            'erc721':config.TRANSFER_TOPIC,
            'erc1155_single':'0x'+'1'*64,
            'erc1155_batch':'0x'+'2'*64,
            'hoodsea_launch':'0x'+'3'*64,
            'hoodsea_sold':'0x'+'4'*64,
            'seaport_fulfilled':'0x'+'5'*64,
        }
        s._selectors={};s._init_signatures=lambda:None;s._stage=lambda *a,**k:None
        s.max_ingest_range_blocks=128
        return s

    def test_one_batch_fetch_and_one_block_timestamp_batch(self):
        s=self._scanner();added=s._scan_range_or_raise(100,110)
        self.assertEqual(added,1)
        self.assertEqual(len(s.ingest_rpc.batch_calls),1)
        self.assertEqual(len(s.ingest_rpc.batch_calls[0]),6)
        self.assertEqual(s.ingest_rpc.block_calls,[[101]])
        self.assertEqual(len(s.db.mints),1)
        self.assertEqual(s.db.mints[0]['block_time'],100)

    def test_timestamp_failure_happens_before_any_sqlite_write(self):
        s=self._scanner(block_ok=False)
        with self.assertRaises(RPCError):s._scan_range_or_raise(100,110)
        self.assertEqual(s.db.mints,[])
        self.assertEqual(s.db.launches,[])
        self.assertEqual(s.db.sales,[])

    def test_catchup_caps_each_checkpoint_range_to_128_blocks(self):
        s=self._scanner();ranges=[];checkpoints=[]
        s._scan_range_or_raise=lambda a,b:ranges.append((a,b))
        s._checkpoint=lambda n:checkpoints.append(n)
        processed,count=s._catch_up(1,300,5000,50)
        self.assertEqual(ranges,[(1,128),(129,256),(257,300)])
        self.assertEqual(checkpoints,[128,256,300])
        self.assertEqual(processed,300)
        self.assertEqual(count,3)


if __name__=='__main__':unittest.main()
