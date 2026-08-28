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
CREATE TABLE IF NOT EXISTS market_events(
  event_id TEXT PRIMARY KEY,
  block_number INTEGER NOT NULL,
  block_time INTEGER NOT NULL,
  tx_hash TEXT NOT NULL,
  log_index INTEGER NOT NULL,
  collection TEXT NOT NULL,
  event_type TEXT NOT NULL,
  token_id TEXT,
  price_wei TEXT,
  seller TEXT,
  buyer TEXT,
  raw_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_collection_time ON market_events(collection, block_time);
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

    def add_market_sale(self, x):
        self.conn.execute("""INSERT OR IGNORE INTO market_events(event_id,block_number,block_time,tx_hash,log_index,collection,event_type,token_id,price_wei,seller,buyer,raw_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (x['event_id'],x['block_number'],x['block_time'],x['tx_hash'],x['log_index'],x['collection'],x.get('event_type','NFT_SOLD'),x.get('token_id'),str(x.get('price_wei')) if x.get('price_wei') is not None else None,x.get('seller'),x.get('buyer'),json.dumps(x.get('raw',{}),separators=(',',':'))))
        self.conn.commit()

    def market_window(self, collection, since_ts):
        rows=self.conn.execute('SELECT * FROM market_events WHERE lower(collection)=lower(?) AND block_time>=? ORDER BY block_time DESC',(collection,since_ts)).fetchall()
        return [dict(r) for r in rows]

    def total_market_sales(self):
        r=self.conn.execute("SELECT COUNT(*) n FROM market_events WHERE event_type='NFT_SOLD'").fetchone()
        return int(r['n'])

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

# V1.1 learning helpers are attached here to keep the SQLite surface compact.
def _ensure_learning_schema(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS shadow_positions(
      collection TEXT PRIMARY KEY,
      first_observed INTEGER NOT NULL,
      last_observed INTEGER NOT NULL,
      entry_score REAL NOT NULL,
      entry_action TEXT NOT NULL,
      entry_floor_eth REAL,
      last_floor_eth REAL,
      peak_floor_eth REAL
    );
    ''')
    conn.commit()


def _observe_shadow(self, candidate, now=None):
    now=int(now or time.time())
    if float(candidate.get('score') or 0) < 60:
        return
    market=candidate.get('market') or {}
    floor=market.get('floor_price')
    try: floor=float(floor) if floor is not None else None
    except Exception: floor=None
    _ensure_learning_schema(self.conn)
    row=self.conn.execute('SELECT * FROM shadow_positions WHERE lower(collection)=lower(?)',(candidate['collection'],)).fetchone()
    if row is None:
        self.conn.execute('INSERT INTO shadow_positions(collection,first_observed,last_observed,entry_score,entry_action,entry_floor_eth,last_floor_eth,peak_floor_eth) VALUES(?,?,?,?,?,?,?,?)',
          (candidate['collection'],now,now,float(candidate.get('score') or 0),candidate.get('action') or 'WATCH',floor,floor,floor))
    else:
        entry=row['entry_floor_eth'] if row['entry_floor_eth'] is not None else floor
        peak=row['peak_floor_eth']
        if floor is not None: peak=max(float(peak or floor),floor)
        self.conn.execute('UPDATE shadow_positions SET last_observed=?,entry_floor_eth=?,last_floor_eth=?,peak_floor_eth=? WHERE collection=?',(now,entry,floor,peak,row['collection']))
    self.conn.commit()


def _shadow_stats(self):
    _ensure_learning_schema(self.conn)
    rows=self.conn.execute('SELECT * FROM shadow_positions').fetchall()
    marked=[r for r in rows if r['entry_floor_eth'] not in (None,0) and r['peak_floor_eth'] is not None]
    doubled=sum(1 for r in marked if float(r['peak_floor_eth']) >= 2*float(r['entry_floor_eth']))
    tenx=sum(1 for r in marked if float(r['peak_floor_eth']) >= 10*float(r['entry_floor_eth']))
    return {'tracked':len(rows),'marked':len(marked),'reached_2x':doubled,'reached_10x':tenx}


def _record_outcome(self, collection, decision, entry_cost_usd, exit_value_usd, gas_usd=0.0, package_id=None):
    net=float(exit_value_usd)-float(entry_cost_usd)-float(gas_usd)
    self.conn.execute('INSERT INTO outcomes(collection,package_id,decision,entry_cost_usd,exit_value_usd,gas_usd,realized_net_usd,recorded_at) VALUES(?,?,?,?,?,?,?,?)',
      (collection,package_id,decision,float(entry_cost_usd),float(exit_value_usd),float(gas_usd),net,int(time.time())))
    self.conn.commit(); return net


def _outcome_stats(self):
    rows=self.conn.execute("SELECT * FROM outcomes WHERE upper(decision) IN ('MINT','BUY') ORDER BY recorded_at").fetchall()
    capital=sum(float(r['entry_cost_usd'] or 0)+float(r['gas_usd'] or 0) for r in rows)
    net=sum(float(r['realized_net_usd'] or 0) for r in rows)
    wins=sum(1 for r in rows if float(r['realized_net_usd'] or 0)>0)
    days=max(1.0, ((int(rows[-1]['recorded_at'])-int(rows[0]['recorded_at']))/86400.0) if len(rows)>1 else 1.0)
    net_capital_day=(100.0*net/capital/days) if capital>0 else 0.0
    return {'samples':len(rows),'capital_deployed_usd':capital,'realized_net_usd':net,'win_rate_pct':(100*wins/len(rows) if rows else 0.0),'net_capital_day_pct':net_capital_day,'observation_days':days}

RadarDB.observe_shadow=_observe_shadow
RadarDB.shadow_stats=_shadow_stats
RadarDB.record_outcome=_record_outcome
RadarDB.outcome_stats=_outcome_stats
