import os
import sqlite3
import tempfile
import unittest

from radar.db import RadarDB


U256_MAX=(1<<256)-1


def _mint(event_id='e1',quantity=1):
    return {
        'event_id':event_id,
        'block_number':100,
        'block_time':1_780_000_000,
        'tx_hash':'0xabc',
        'log_index':1,
        'collection':'0x0000000000000000000000000000000000000001',
        'standard':'ERC1155',
        'recipient':'0x0000000000000000000000000000000000000002',
        'quantity':quantity,
        'token_id':'7',
        'raw':{},
    }


class DBUint256Tests(unittest.TestCase):
    def test_huge_erc1155_quantity_roundtrips_and_sums_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            db=RadarDB(os.path.join(td,'radar.sqlite'))
            try:
                db.add_mint(_mint(quantity=U256_MAX))
                row=db.mint_window('0x0000000000000000000000000000000000000001',0)[0]
                self.assertEqual(int(row['quantity']),U256_MAX)
                self.assertEqual(db.total_mints(),U256_MAX)
                recent=db.recent_collections(0)
                self.assertEqual(int(recent[0]['minted']),U256_MAX)
                self.assertEqual(db.integrity_check(),'ok')
            finally:
                db.close()

    def test_huge_launch_uint256_is_text_not_sqlite_integer(self):
        with tempfile.TemporaryDirectory() as td:
            db=RadarDB(os.path.join(td,'radar.sqlite'))
            try:
                db.add_launch({
                    'tx_hash':'0xlaunch',
                    'block_number':101,
                    'block_time':1_780_000_001,
                    'collection':'0x0000000000000000000000000000000000000003',
                    'creator':'0x0000000000000000000000000000000000000004',
                    'name':'Huge',
                    'ticker':'HUGE',
                    'mint_price_wei':U256_MAX,
                    'mint_start':U256_MAX,
                    'raw':{},
                })
                launch=db.launches_map()['0x0000000000000000000000000000000000000003']
                self.assertEqual(int(launch['mint_price_wei']),U256_MAX)
                self.assertEqual(int(launch['mint_start']),U256_MAX)
            finally:
                db.close()

    def test_legacy_integer_columns_migrate_without_losing_rows(self):
        with tempfile.TemporaryDirectory() as td:
            path=os.path.join(td,'radar.sqlite')
            conn=sqlite3.connect(path)
            conn.executescript('''
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE launches(tx_hash TEXT PRIMARY KEY,block_number INTEGER NOT NULL,block_time INTEGER NOT NULL,collection TEXT NOT NULL,creator TEXT,name TEXT,ticker TEXT,mint_price_wei TEXT,mint_start INTEGER,raw_json TEXT NOT NULL);
CREATE TABLE mint_events(event_id TEXT PRIMARY KEY,block_number INTEGER NOT NULL,block_time INTEGER NOT NULL,tx_hash TEXT NOT NULL,log_index INTEGER NOT NULL,collection TEXT NOT NULL,standard TEXT NOT NULL,recipient TEXT,quantity INTEGER NOT NULL DEFAULT 1,token_id TEXT,raw_json TEXT NOT NULL);
CREATE INDEX idx_mint_collection_time ON mint_events(collection,block_time);
INSERT INTO mint_events VALUES('legacy',1,100,'0xtx',0,'0x0000000000000000000000000000000000000001','ERC1155','0x2',7,'1','{}');
INSERT INTO launches VALUES('0xold',1,100,'0x0000000000000000000000000000000000000003','0x4','Old','OLD','0',123,'{}');
''')
            conn.commit();conn.close()

            db=RadarDB(path)
            try:
                mint_type={r[1]:r[2] for r in db.conn.execute('PRAGMA table_info(mint_events)')}['quantity'].upper()
                launch_type={r[1]:r[2] for r in db.conn.execute('PRAGMA table_info(launches)')}['mint_start'].upper()
                self.assertEqual(mint_type,'TEXT')
                self.assertEqual(launch_type,'TEXT')
                self.assertEqual(db.total_mints(),7)
                self.assertEqual(int(db.mint_window('0x0000000000000000000000000000000000000001',0)[0]['quantity']),7)
                db.add_mint(_mint(event_id='huge-after-migration',quantity=U256_MAX))
                self.assertEqual(db.total_mints(),U256_MAX+7)
            finally:
                db.close()


if __name__=='__main__':
    unittest.main()
