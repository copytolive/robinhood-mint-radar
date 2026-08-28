import unittest
from radar.scanner import decode_erc1155_batch

def w(n):return int(n).to_bytes(32,'big')
class BatchTests(unittest.TestCase):
    def test_batch_values(self):
        # offsets 64 and 160, arrays [1,2] and [3,4]
        raw=w(64)+w(160)+w(2)+w(1)+w(2)+w(2)+w(3)+w(4)
        out=decode_erc1155_batch('0x'+raw.hex())
        self.assertEqual(out,[('1',3),('2',4)])
