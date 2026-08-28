import unittest
from unittest.mock import patch
from radar import config
import radar.live_scanner as live_mod
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


class _RPC:
    def __init__(self,tip=12000): self.tip=tip
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
        s.build_status=lambda tip,safe,first,to,started:{'chain':{'safe_block':safe},'scan':{'from_block':first,'to_block':to},'live_ready':'READY','money_readiness':'WAIT FOR QUALIFIED OPPORTUNITY','watchlist':[],'best_live_observation':None,'manual_packages':[],'diagnostics':[]}
        return s

    def test_standard_abi_hashes_do_not_hit_rpc(self):
        class SigRPC:
            def __init__(self): self.calls=[]
            def sha3_text(self,sig):
                self.calls.append(sig)
                return '0x'+('11' if sig.startswith('CollectionLaunched') else '22')*32
        live_mod._DYNAMIC_TOPIC_CACHE.clear()
        s=LiveRadarScanner.__new__(LiveRadarScanner)
        s.rpc=SigRPC();s.diag=[];s._topics={};s._selectors={}
        s._init_signatures()
        self.assertEqual(len(s.rpc.calls),2)
        self.assertEqual(s._topics['erc1155_single'],'0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62')
        self.assertEqual(s._topics['erc1155_batch'],'0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07e595d983b8c0526c8f7fb')
        self.assertEqual(s._topics['seaport_fulfilled'],'0x9d9af8e38d66c62e2c12f0225249fd9d721c54b83f48d9352c97c6cacdcb6f31')
        self.assertEqual(s._selectors['supports'],'0x01ffc9a7')
        self.assertEqual(s._selectors['totalSupply'],'0x18160ddd')
        self.assertEqual(s._selectors['totalMinted'],'0xa2309ff8')
        self.assertEqual(s._selectors['maxSupply'],'0xd5abeb01')

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
