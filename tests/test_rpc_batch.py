import unittest
from unittest.mock import patch

from radar.rpc import RPCClient,RPCError


class _BatchResp:
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self):
        return b'[{"jsonrpc":"2.0","id":2,"result":"0x1233"},{"jsonrpc":"2.0","id":1,"result":"0x1234"}]'


class RPCBatchTests(unittest.TestCase):
    def test_batch_call_preserves_request_order_even_if_response_reordered(self):
        c=RPCClient('https://example.invalid',retries=0,fallback_urls=[],expected_chain_id=None)
        with patch('radar.rpc.urlopen',return_value=_BatchResp()):
            out=c.batch_call([('eth_blockNumber',[]),('eth_chainId',[])])
        self.assertEqual(out,['0x1234','0x1233'])

    def test_blocks_falls_back_to_concurrent_single_reads_if_batch_is_unsupported(self):
        c=RPCClient('https://example.invalid',retries=0,fallback_urls=[],expected_chain_id=None)
        with patch.object(c,'batch_call',side_effect=RPCError('batch unsupported')),patch.object(c,'block',side_effect=lambda n:{'number':hex(n),'timestamp':hex(100+n)}):
            out=c.blocks([1,2,3],batch_size=64,max_workers=3)
        self.assertEqual(sorted(out),[1,2,3])
        self.assertEqual(out[3]['timestamp'],hex(103))


if __name__=='__main__':unittest.main()
