import json
import unittest
from unittest.mock import patch
from radar.rpc import RPCClient,RPCError


class _Resp:
    def __init__(self,result):self.result=result
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self):return json.dumps({'jsonrpc':'2.0','id':1,'result':self.result}).encode()


def _method(req):
    return json.loads(req.data.decode())['method']


class RPCFailoverTests(unittest.TestCase):
    def test_official_reset_fails_over_only_after_chain_verification(self):
        calls=[]
        def fake(req,timeout=None):
            calls.append((req.full_url,_method(req)))
            if req.full_url.startswith('https://rpc.mainnet.chain.robinhood.com'):
                raise ConnectionResetError(54,'reset')
            if _method(req)=='eth_chainId':return _Resp('0x1237')
            if _method(req)=='eth_blockNumber':return _Resp('0x64')
            raise AssertionError(_method(req))
        c=RPCClient('https://rpc.mainnet.chain.robinhood.com',timeout=1,retries=0)
        with patch('radar.rpc.urlopen',side_effect=fake):
            self.assertEqual(c.block_number(),100)
        self.assertNotEqual(c.url,'https://rpc.mainnet.chain.robinhood.com')
        self.assertGreaterEqual(c.failovers,1)
        self.assertIn((c.url,'eth_chainId'),calls)
        self.assertIn((c.url,'eth_blockNumber'),calls)

    def test_wrong_chain_fallback_is_rejected(self):
        def fake(req,timeout=None):
            if req.full_url.startswith('https://rpc.mainnet.chain.robinhood.com'):
                raise ConnectionResetError(54,'reset')
            return _Resp('0x1')
        with patch.dict('os.environ',{'RH_RPC_FALLBACK_URLS':'https://wrong.example/rpc'}):
            c=RPCClient('https://rpc.mainnet.chain.robinhood.com',timeout=1,retries=0)
            with patch('radar.rpc.urlopen',side_effect=fake):
                with self.assertRaises(RPCError):c.block_number()

    def test_non_robinhood_dummy_endpoint_does_not_auto_add_public_fallbacks(self):
        c=RPCClient('https://example.invalid',timeout=1,retries=0)
        self.assertEqual(c.urls,['https://example.invalid'])
        self.assertIsNone(c.expected_chain_id)


if __name__=='__main__':unittest.main()
