import json
import os
import sqlite3
import time

SCHEMA = '''
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS launches(
  tx_hash TEXT PRIMARY KEY,
  block_number INTEGER NOT NULL,
  block_time INTEGER NOT NULL,
  collection TEXT NOT NULL,
  creator TEXT,
  name TEXT,
  ticker TEXT,
  mint_price_wei TEXT,
  mint_start INTEGER,
  raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mint_events(
  event_id TEXT PRIMARY KEY,
  block_number INTEGER NOT NULL,
  block_time INTEGER NOT NULL,
  tx_hash TEXT NOT NULL,
  log_index INTEGER NOT NULL,
  collection TEXT NOT NULL,
  standard TEXT NOT NULL,
  recipient TEXT,
  quantity INTEGER NOT NULL DEFAULT 1,
  token_id TEXT,
  raw_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mint_collection_time ON mint_events(collection, block_time);
CREATE TABLE IF NOT EXISTS observations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  observed_at INTEGER NOT NULL,
  collection TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_collection_time ON observations(collection, observed_at);
CREATE TABLE IF NOT EXISTS outcomes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  collection TEXT NOT NULL,
  package_id TEXT,
  decision TEXT,
  entry_cost_usd REAL,
  exit_value_usd REAL,
  gas_usd REAL,
  realized_net_usd REAL,
  recorded_at INTEGER NOT NULL
);
'''

class RadarDB:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def set_meta(self, key, value):
        self.conn.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))
        self.conn.commit()

    def get_meta(self, key, default=None):
        r = self.conn.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        return r['value'] if r else default

    def last_block(self):
        v = self.get_meta('last_block')
        return int(v) if v is not None else None

    def add_launch(self, x):
        self.conn.execute('''INSERT OR IGNORE INTO launches(tx_hash,block_number,block_time,collection,creator,name,ticker,mint_price_wei,mint_start,raw_json)
        VALUES(?,?,?,?,?,?,?,?,?,?)''', (x['tx_hash'],x['block_number'],x['block_time'],x['collection'],x.get('creator'),x.get('name'),x.get('ticker'),str(x.get('mint_price_wei')) if x.get('mint_price_wei') is not None else None,x.get('mint_start'),json.dumps(x.get('raw',{}),separators=(',',':'))))
        self.conn.commit()

    def add_mint(self, x):
        self.conn.execute('''INSERT OR IGNORE INTO mint_events(event_id,block_number,block_time,tx_hash,log_index,collection,standard,recipient,quantity,token_id,raw_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (x['event_id'],x['block_number'],x['block_time'],x['tx_hash'],x['log_index'],x['collection'],x['standard'],x.get('recipient'),int(x.get('quantity',1)),x.get('token_id'),json.dumps(x.get('raw',{}),separators=(',',':'))))
        self.conn.commit()

    def launches_map(self):
        rows=self.conn.execute('SELECT * FROM launches').fetchall()
        return {r['collection'].lower():dict(r) for r in rows}

    def recent_collections(self, since_ts):
        rows=self.conn.execute('''SELECT collection, standard, SUM(quantity) minted, COUNT(*) events, COUNT(DISTINCT recipient) recipients, MAX(block_time) last_time
        FROM mint_events WHERE block_time>=? GROUP BY collection,standard ORDER BY last_time DESC''',(since_ts,)).fetchall()
        return [dict(r) for r in rows]

    def mint_window(self, collection, since_ts):
        rows=self.conn.execute('SELECT recipient,quantity,block_time FROM mint_events WHERE lower(collection)=lower(?) AND block_time>=?',(collection,since_ts)).fetchall()
        return [dict(r) for r in rows]

    def total_mints(self):
        r=self.conn.execute('SELECT COALESCE(SUM(quantity),0) n FROM mint_events').fetchone()
        return int(r['n'])

    def total_launches(self):
        r=self.conn.execute('SELECT COUNT(*) n FROM launches').fetchone()
        return int(r['n'])

    def add_observation(self, collection, payload):
        self.conn.execute('INSERT INTO observations(observed_at,collection,payload) VALUES(?,?,?)',(int(time.time()),collection,json.dumps(payload,separators=(',',':'))))
        self.conn.commit()
