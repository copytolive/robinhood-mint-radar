import unittest
from radar.seaport import decode_order_fulfilled,sale_records

def w(n): return int(n).to_bytes(32,'big')
def aw(addr): return bytes.fromhex('00'*12+addr[2:])

class SeaportTests(unittest.TestCase):
    def test_simple_native_to_erc721_sale(self):
        nft='0x'+'ab'*20
        recipient='0x'+'cd'*20
        seller='0x'+'ef'*20
        header=(b'\x11'*32)+aw(recipient)+w(128)+w(288)
        offer=w(1)+w(2)+aw(nft)+w(1466)+w(1)
        consideration=w(1)+w(0)+aw('0x'+'00'*20)+w(0)+w(400_000_000_000_000)+aw(seller)
        data='0x'+(header+offer+consideration).hex()
        topics=['0x'+'00'*32,'0x'+'00'*12+seller[2:],'0x'+'00'*32]
        event=decode_order_fulfilled(data,topics)
        sales=sale_records(event)
        self.assertEqual(len(sales),1)
        self.assertEqual(sales[0]['collection'].lower(),nft.lower())
        self.assertEqual(sales[0]['token_id'],'1466')
        self.assertEqual(sales[0]['price_wei'],400_000_000_000_000)
