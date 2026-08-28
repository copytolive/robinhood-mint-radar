import json
import os
import sqlite3
import time
from .calibration import probability_from_score


class _ExactIntSum:
    """SQLite aggregate that sums arbitrary-size decimal integers exactly."""
    def __init__(self):
        self.total=0
    def step(self,value):
        if value not in (None,''):
            self.total+=int(value)
    def finalize(self):
        return str(self.total)


SCHEMA='''
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS launches(tx_hash TEXT PRIMARY KEY,block_number INTEGER NOT NULL,block_time INTEGER NOT NULL,collection TEXT NOT NULL,creator TEXT,name TEXT,ticker TEXT,mint_price_wei TEXT,mint_start TEXT,raw_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mint_events(event_id TEXT PRIMARY KEY,block_number INTEGER NOT NULL,block_time INTEGER NOT NULL,tx_hash TEXT NOT NULL,log_index INTEGER NOT NULL,collection TEXT NOT NULL,standard TEXT NOT NULL,recipient TEXT,quantity TEXT NOT NULL DEFAULT '1',token_id TEXT,raw_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_mint_collection_time ON mint_events(collection,block_time);
CREATE TABLE IF NOT EXISTS market_events(event_id TEXT PRIMARY KEY,block_number INTEGER NOT NULL,block_time INTEGER NOT NULL,tx_hash TEXT NOT NULL,log_index INTEGER NOT NULL,collection TEXT NOT NULL,event_type TEXT NOT NULL,token_id TEXT,price_wei TEXT,seller TEXT,buyer TEXT,raw_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_market_collection_time ON market_events(collection,block_time);
CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY AUTOINCREMENT,observed_at INTEGER NOT NULL,collection TEXT NOT NULL,payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_obs_collection_time ON observations(collection,observed_at);
CREATE TABLE IF NOT EXISTS outcomes(id INTEGER PRIMARY KEY AUTOINCREMENT,collection TEXT NOT NULL,package_id TEXT,decision TEXT,entry_cost_usd REAL,exit_value_usd REAL,gas_usd REAL,realized_net_usd REAL,recorded_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS shadow_positions(collection TEXT PRIMARY KEY,first_observed INTEGER NOT NULL,last_observed INTEGER NOT NULL,entry_score REAL NOT NULL,entry_action TEXT NOT NULL,entry_probability REAL,entry_floor_eth REAL,last_floor_eth REAL,peak_floor_eth REAL);
'''


class RadarDB:
    def __init__(self,path):
        self.path=path; os.makedirs(os.path.dirname(path) or '.',exist_ok=True)
        self.conn=sqlite3.connect(path,timeout=5.0); self.conn.row_factory=sqlite3.Row
        self.conn.create_aggregate('EXACT_INT_SUM',1,_ExactIntSum)
        self.conn.execute('PRAGMA foreign_keys=ON'); self.conn.execute('PRAGMA busy_timeout=5000'); self.conn.execute('PRAGMA synchronous=NORMAL')
        try:self.conn.execute('PRAGMA journal_mode=WAL')
        except sqlite3.DatabaseError:pass
        self.conn.executescript(SCHEMA); self._migrate(); self.conn.commit()
    def _columns(self,t):return {r[1] for r in self.conn.execute(f'PRAGMA table_info({t})').fetchall()}
    def _column_type(self,t,n):
        for r in self.conn.execute(f'PRAGMA table_info({t})').fetchall():
            if r[1]==n:return (r[2] or '').upper()
        return None
    def _ensure_col(self,t,n,d):
        if n not in self._columns(t):self.conn.execute(f'ALTER TABLE {t} ADD COLUMN {n} {d}')
    def _migrate_uint256_columns(self):
        # Solidity quantities are uint256. Python's sqlite3 driver only accepts
        # signed 64-bit INTEGER bindings, so contract values must be persisted
        # as exact decimal TEXT. Rebuild legacy tables atomically when needed.
        if self._column_type('mint_events','quantity')!='TEXT':
            self.conn.executescript('''
BEGIN IMMEDIATE;
ALTER TABLE mint_events RENAME TO mint_events_legacy_u256;
CREATE TABLE mint_events(event_id TEXT PRIMARY KEY,block_number INTEGER NOT NULL,block_time INTEGER NOT NULL,tx_hash TEXT NOT NULL,log_index INTEGER NOT NULL,collection TEXT NOT NULL,standard TEXT NOT NULL,recipient TEXT,quantity TEXT NOT NULL DEFAULT '1',token_id TEXT,raw_json TEXT NOT NULL);
INSERT INTO mint_events(event_id,block_number,block_time,tx_hash,log_index,collection,standard,recipient,quantity,token_id,raw_json)
SELECT event_id,block_number,block_time,tx_hash,log_index,collection,standard,recipient,CAST(quantity AS TEXT),token_id,raw_json FROM mint_events_legacy_u256;
DROP TABLE mint_events_legacy_u256;
CREATE INDEX IF NOT EXISTS idx_mint_collection_time ON mint_events(collection,block_time);
COMMIT;
''')
        if self._column_type('launches','mint_start')!='TEXT':
            self.conn.executescript('''
BEGIN IMMEDIATE;
ALTER TABLE launches RENAME TO launches_legacy_u256;
CREATE TABLE launches(tx_hash TEXT PRIMARY KEY,block_number INTEGER NOT NULL,block_time INTEGER NOT NULL,collection TEXT NOT NULL,creator TEXT,name TEXT,ticker TEXT,mint_price_wei TEXT,mint_start TEXT,raw_json TEXT NOT NULL);
INSERT INTO launches(tx_hash,block_number,block_time,collection,creator,name,ticker,mint_price_wei,mint_start,raw_json)
SELECT tx_hash,block_number,block_time,collection,creator,name,ticker,mint_price_wei,CASE WHEN mint_start IS NULL THEN NULL ELSE CAST(mint_start AS TEXT) END,raw_json FROM launches_legacy_u256;
DROP TABLE launches_legacy_u256;
COMMIT;
''')
    def _migrate(self):
        self._migrate_uint256_columns()
        for n,d in [('payment_token','TEXT'),('payment_amount','TEXT'),('source','TEXT'),('order_hash','TEXT'),('bundle_size','INTEGER DEFAULT 1')]:self._ensure_col('market_events',n,d)
        for n,d in [('predicted_score','REAL'),('predicted_probability','REAL')]:self._ensure_col('outcomes',n,d)
        self._ensure_col('shadow_positions','entry_probability','REAL')
    def close(self):self.conn.close()
    def set_meta(self,k,v):self.conn.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,str(v))); self.conn.commit()
    def get_meta(self,k,default=None):
        r=self.conn.execute('SELECT value FROM meta WHERE key=?',(k,)).fetchone(); return r['value'] if r else default
    def last_block(self):
        v=self.get_meta('last_block'); return int(v) if v is not None else None
    def add_launch(self,x):
        mint_start=x.get('mint_start')
        self.conn.execute('INSERT OR IGNORE INTO launches(tx_hash,block_number,block_time,collection,creator,name,ticker,mint_price_wei,mint_start,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?)',(x['tx_hash'],x['block_number'],x['block_time'],x['collection'],x.get('creator'),x.get('name'),x.get('ticker'),str(x.get('mint_price_wei')) if x.get('mint_price_wei') is not None else None,str(int(mint_start)) if mint_start is not None else None,json.dumps(x.get('raw',{}),separators=(',',':')))); self.conn.commit()
    def add_mint(self,x):
        quantity=str(int(x.get('quantity',1)))
        self.conn.execute('INSERT OR IGNORE INTO mint_events(event_id,block_number,block_time,tx_hash,log_index,collection,standard,recipient,quantity,token_id,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(x['event_id'],x['block_number'],x['block_time'],x['tx_hash'],x['log_index'],x['collection'],x['standard'],x.get('recipient'),quantity,x.get('token_id'),json.dumps(x.get('raw',{}),separators=(',',':')))); self.conn.commit()
    def add_market_sale(self,x):
        self.conn.execute('INSERT OR IGNORE INTO market_events(event_id,block_number,block_time,tx_hash,log_index,collection,event_type,token_id,price_wei,seller,buyer,raw_json,payment_token,payment_amount,source,order_hash,bundle_size) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(x['event_id'],x['block_number'],x['block_time'],x['tx_hash'],x['log_index'],x['collection'],x.get('event_type','NFT_SOLD'),x.get('token_id'),str(x.get('price_wei')) if x.get('price_wei') is not None else None,x.get('seller'),x.get('buyer'),json.dumps(x.get('raw',{}),separators=(',',':')),x.get('payment_token'),str(x.get('payment_amount')) if x.get('payment_amount') is not None else None,x.get('source'),x.get('order_hash'),int(x.get('bundle_size') or 1))); self.conn.commit()
    def market_window(self,c,s):return [dict(r) for r in self.conn.execute('SELECT * FROM market_events WHERE lower(collection)=lower(?) AND block_time>=? ORDER BY block_time DESC',(c,s)).fetchall()]
    def market_summary(self,c,s):
        rows=self.market_window(c,s); native=[r for r in rows if r.get('price_wei') not in (None,'') and int(r.get('bundle_size') or 1)==1]; uniq={r.get('order_hash') or r.get('event_id') for r in rows}
        return {'sales_24h':len(uniq),'native_sales_24h':len(native),'volume_eth_24h':sum(int(r['price_wei']) for r in native)/1e18 if native else 0.0,'sources':sorted({r.get('source') or 'ONCHAIN' for r in rows})}
    def total_market_sales(self):return int(self.conn.execute("SELECT COUNT(*) n FROM market_events WHERE event_type='NFT_SOLD'").fetchone()['n'])
    def launches_map(self):return {r['collection'].lower():dict(r) for r in self.conn.execute('SELECT * FROM launches').fetchall()}
    def recent_collections(self,s):
        rows=self.conn.execute('SELECT collection,standard,EXACT_INT_SUM(quantity) minted,COUNT(*) events,COUNT(DISTINCT recipient) recipients,MAX(block_time) last_time FROM mint_events WHERE block_time>=? GROUP BY collection,standard ORDER BY last_time DESC',(s,)).fetchall()
        out=[]
        for r in rows:
            d=dict(r);d['minted']=int(d.get('minted') or 0);out.append(d)
        return out
    def mint_window(self,c,s):return [dict(r) for r in self.conn.execute('SELECT recipient,quantity,block_time,tx_hash,token_id FROM mint_events WHERE lower(collection)=lower(?) AND block_time>=? ORDER BY block_time DESC',(c,s)).fetchall()]
    def total_mints(self):
        r=self.conn.execute('SELECT EXACT_INT_SUM(quantity) n FROM mint_events').fetchone();return int((r['n'] if r else None) or 0)
    def total_launches(self):return int(self.conn.execute('SELECT COUNT(*) n FROM launches').fetchone()['n'])
    def add_observation(self,c,p):self.conn.execute('INSERT INTO observations(observed_at,collection,payload) VALUES(?,?,?)',(int(time.time()),c,json.dumps(p,separators=(',',':'))));self.conn.commit()
    def observe_shadow(self,candidate,now=None):
        now=int(now or time.time());
        if float(candidate.get('score') or 0)<60:return
        floor=(candidate.get('market') or {}).get('floor_price')
        try:floor=float(floor) if floor is not None else None
        except Exception:floor=None
        p=probability_from_score(candidate.get('score')); row=self.conn.execute('SELECT * FROM shadow_positions WHERE lower(collection)=lower(?)',(candidate['collection'],)).fetchone()
        if row is None:self.conn.execute('INSERT INTO shadow_positions(collection,first_observed,last_observed,entry_score,entry_action,entry_probability,entry_floor_eth,last_floor_eth,peak_floor_eth) VALUES(?,?,?,?,?,?,?,?,?)',(candidate['collection'],now,now,float(candidate.get('score') or 0),candidate.get('action') or 'WATCH',p,floor,floor,floor))
        else:
            entry=row['entry_floor_eth'] if row['entry_floor_eth'] is not None else floor; peak=row['peak_floor_eth']; peak=max(float(peak or floor),floor) if floor is not None else peak
            self.conn.execute('UPDATE shadow_positions SET last_observed=?,entry_floor_eth=?,last_floor_eth=?,peak_floor_eth=? WHERE collection=?',(now,entry,floor,peak,row['collection']))
        self.conn.commit()
    def shadow_stats(self):
        rows=self.conn.execute('SELECT * FROM shadow_positions').fetchall(); marked=[r for r in rows if r['entry_floor_eth'] not in (None,0) and r['peak_floor_eth'] is not None]
        return {'tracked':len(rows),'marked':len(marked),'reached_2x':sum(1 for r in marked if float(r['peak_floor_eth'])>=2*float(r['entry_floor_eth'])),'reached_10x':sum(1 for r in marked if float(r['peak_floor_eth'])>=10*float(r['entry_floor_eth']))}
    def record_outcome(self,collection,decision,entry_cost_usd,exit_value_usd,gas_usd=0.0,package_id=None,predicted_score=None,predicted_probability=None):
        net=float(exit_value_usd)-float(entry_cost_usd)-float(gas_usd); predicted_probability=probability_from_score(predicted_score) if predicted_probability is None and predicted_score is not None else predicted_probability
        self.conn.execute('INSERT INTO outcomes(collection,package_id,decision,entry_cost_usd,exit_value_usd,gas_usd,realized_net_usd,recorded_at,predicted_score,predicted_probability) VALUES(?,?,?,?,?,?,?,?,?,?)',(collection,package_id,decision,float(entry_cost_usd),float(exit_value_usd),float(gas_usd),net,int(time.time()),predicted_score,predicted_probability));self.conn.commit();return net
    def outcome_stats(self):
        rows=self.conn.execute("SELECT * FROM outcomes WHERE upper(decision) IN ('MINT','BUY') ORDER BY recorded_at").fetchall(); capital=sum(float(r['entry_cost_usd'] or 0)+float(r['gas_usd'] or 0) for r in rows);net=sum(float(r['realized_net_usd'] or 0) for r in rows);wins=sum(1 for r in rows if float(r['realized_net_usd'] or 0)>0);days=max(1.0,((int(rows[-1]['recorded_at'])-int(rows[0]['recorded_at']))/86400.0) if len(rows)>1 else 1.0)
        return {'samples':len(rows),'capital_deployed_usd':capital,'realized_net_usd':net,'win_rate_pct':100*wins/len(rows) if rows else 0.0,'net_capital_day_pct':100.0*net/capital/days if capital>0 else 0.0,'observation_days':days}
    def calibration_samples(self):
        rows=self.conn.execute("SELECT predicted_probability,realized_net_usd FROM outcomes WHERE predicted_probability IS NOT NULL AND upper(decision) IN ('MINT','BUY')").fetchall();out=[{'predicted_probability':r['predicted_probability'],'outcome':1 if float(r['realized_net_usd'] or 0)>0 else 0} for r in rows]
        for r in self.conn.execute('SELECT * FROM shadow_positions WHERE entry_probability IS NOT NULL AND entry_floor_eth IS NOT NULL AND peak_floor_eth IS NOT NULL AND last_observed-first_observed>=86400').fetchall():out.append({'predicted_probability':r['entry_probability'],'outcome':1 if float(r['peak_floor_eth'])>=2*float(r['entry_floor_eth']) else 0})
        return out
    def integrity_check(self):
        r=self.conn.execute('PRAGMA integrity_check').fetchone();return r[0] if r else 'unknown'
    def maintenance(self,now=None,observation_days=30,event_days=90):
        now=int(now or time.time());last=int(self.get_meta('last_maintenance','0') or 0)
        if now-last<21600:return {'ran':False,'integrity':self.integrity_check()}
        self.conn.execute('DELETE FROM observations WHERE observed_at<?',(now-observation_days*86400,));self.conn.execute('DELETE FROM mint_events WHERE block_time<?',(now-event_days*86400,));self.conn.execute('DELETE FROM market_events WHERE block_time<?',(now-event_days*86400,));self.conn.commit()
        try:self.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        except sqlite3.DatabaseError:pass
        self.set_meta('last_maintenance',now);return {'ran':True,'integrity':self.integrity_check()}
    def backup(self,backup_dir=None,keep=7):
        backup_dir=backup_dir or os.path.join(os.path.dirname(self.path) or '.','backups');os.makedirs(backup_dir,exist_ok=True);target=os.path.join(backup_dir,f"radar-{time.strftime('%Y%m%d-%H%M%S',time.gmtime())}.sqlite");dst=sqlite3.connect(target)
        try:self.conn.backup(dst)
        finally:dst.close()
        files=sorted([os.path.join(backup_dir,x) for x in os.listdir(backup_dir) if x.endswith('.sqlite')],reverse=True)
        for old in files[keep:]:
            try:os.remove(old)
            except OSError:pass
        return target
    def db_health(self):
        try:size=os.path.getsize(self.path)
        except OSError:size=0
        return {'journal_mode':self.conn.execute('PRAGMA journal_mode').fetchone()[0],'integrity':self.integrity_check(),'bytes':size}
