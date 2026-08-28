import unittest
from unittest.mock import patch
from radar import config
from radar.live_scanner import LiveRadarScanner
from radar.rpc import RPCClient, RPCError


class _DB:
    def __init__(self,last=1000):
        self.last=last
        self.meta={'last_block_hash':'0xhash1000'} if last is not None else {}
    def last_block(self): return self.last
    def get_meta(self,key,default=None): return self.meta.get(key,default)
    def set_meta(self,key,value):
        self.meta[key]=str(value)
        if key=='last_block': self.last=int(value)
    def recent_collections(self,since): return []
    def launches_map(self): return {}


class _RPC:
    def __init__(self,tip=12000):
        self.tip=tip
        self.url='https://example.invalid'
        self.failovers=0
    def chain_id(self): return config.CHAIN_ID
    def block_number(self): return self.tip
    def block(self,n): return {'hash':f'0xhash{n}','timestamp':hex(1000)}


class _Resp:
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self): return b'{"jsonrpc":"2.0","id":2,"result":"0x1234"}'


class LiveScannerTests(unittest.TestCase):
    def _scanner(self,last=1000,tip=12000):
        s=LiveRadarScanner.__new__(LiveRadarScanner)
        s.db=_DB(last);s.rpc=_RPC(tip);s.diag=[];s._topics={};s._selectors={};s._block_time={};s._tx_cache={}
        s._init_signatures=lambda:None
        s._prewarm_enrichment=lambda:None
        s.build_status=lambda tip,safe,first,to,started:{'chain':{'safe_block':safe},'scan':{'from_block':first,'to_block':to},'live_ready':'READY','money_readiness':'WAIT FOR QUALIFIED OPPORTUNITY','watchlist':[],'best_live_observation':None,'manual_packages':[],'diagnostics':[]}
        return s

    def test_signature_initialization_is_fully_rpc_free(self):
        class SigRPC:
            def sha3_text(self,sig): raise AssertionError('web3_sha3 must not be called')
            def selector(self,sig): raise AssertionError('selector RPC must not be called')
        s=LiveRadarScanner.__new__(LiveRadarScanner)
        s.rpc=SigRPC();s.diag=[];s._topics={};s._selectors={}
        s._init_signatures()
        self.assertEqual(s._topics['erc1155_single'],'0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62')
        self.assertEqual(s._topics['erc1155_batch'],'0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07e595d983b8c0526c8f7fb')
        self.assertEqual(s._topics['hoodsea_launch'],'0x107c8d1b9a64f45bbe60918da1ac5b35998371338b84776cfdc6ddaaee66e3fd')
        self.assertEqual(s._topics['hoodsea_sold'],'0x2820044bbebd591ee7d08b7d81dd01945a1a32706da693a946e532d6d9884258')
        self.assertEqual(s._topics['seaport_fulfilled'],'0x9d9af8e38d66c62e2c12f0225249fd9d721c54b83f48d9352c97c6cacdcb6f31')
        self.assertEqual(s._selectors['supports'],'0x01ffc9a7')
        self.assertEqual(s._selectors['mintPrice'],'0x6817c76c')
        self.assertEqual(s._selectors['mintPriceWei'],'0xcb2c9722')
        self.assertEqual(s._selectors['info'],'0x370158ea')

    def test_zero_price_inference_uses_bounded_enrichment_rpc(self):
        class LongRPC:
            def transaction(self,txh): raise AssertionError('long ingest RPC must not be used for mint tx inference')
        class EnrichRPC:
            def transaction(self,txh): return {'value':'0x0'}
        s=LiveRadarScanner.__new__(LiveRadarScanner)
        s.rpc=LongRPC();s.enrich_rpc=EnrichRPC();s._tx_cache={}
        self.assertEqual(s._observed_zero_price([{'tx_hash':'0xabc'}]),(0,'OBSERVED_MINT_TX_VALUE_ZERO'))

    def test_backlog_is_consumed_in_multiple_chunks_before_status(self):
        s=self._scanner(last=1000,tip=12000);ranges=[]
        s._scan_range_or_raise=lambda a,b:ranges.append((a,b))
        with patch.object(config,'CHUNK_BLOCKS',5000),patch.object(config,'MAX_CATCHUP_BLOCKS',5000):
            out=s.scan_once()
        self.assertEqual(ranges,[(1001,6000),(6001,11000),(11001,11990)])
        self.assertEqual(s.db.last,11990)
        self.assertEqual(out['scan']['from_block'],1001)
        self.assertEqual(out['scan']['to_block'],11990)
        self.assertEqual(out['scan']['lag_seconds'],0)

    def test_recorded_historical_gap_is_visible_in_status(self):
        s=self._scanner(last=11900,tip=12000);s._scan_range_or_raise=lambda a,b:None
        s.db.meta['historical_gap_from']='1001';s.db.meta['historical_gap_to']='11899'
        out=s.scan_once()
        self.assertEqual(out['scan']['historical_gap'],{'state':'RECORDED_NOT_BACKFILLED','from_block':1001,'to_block':11899,'blocks':10899})

    def test_failed_range_does_not_advance_checkpoint(self):
        s=self._scanner(last=1000,tip=12000)
        def fail(a,b): raise RPCError('boom')
        s._scan_range_or_raise=fail
        with self.assertRaises(RPCError): s.scan_once()
        self.assertEqual(s.db.last,1000)

    def test_rpc_log_range_bisects_after_provider_rejection(self):
        c=RPCClient('https://example.invalid');calls=[]
        def fake(a,b,topics,address=None):
            calls.append((a,b))
            if b-a>=2: raise RPCError('range too large')
            return [{'blockNumber':hex(a)},{'blockNumber':hex(b)}] if a!=b else [{'blockNumber':hex(a)}]
        c._logs_once=fake
        rows=c.logs(1,4,['0xtopic'])
        self.assertEqual([int(r['blockNumber'],16) for r in rows],[1,2,3,4])
        self.assertGreater(len(calls),1)

    def test_rpc_call_retries_connection_reset(self):
        c=RPCClient('https://example.invalid',retries=1)
        with patch('radar.rpc.urlopen',side_effect=[ConnectionResetError(54,'reset'),_Resp()]),patch('radar.rpc.time.sleep'):
            self.assertEqual(c.call('eth_blockNumber'),'0x1234')


if __name__=='__main__': unittest.main()
