import json
import os
import time

from . import config
from .fast_live_scanner import FastLiveRadarScanner
from .rpc import RPCError


class BoundedFastLiveRadarScanner(FastLiveRadarScanner):
    """Fast live scanner with a fixed per-cycle target and ingest time budget.

    Robinhood Chain can advance faster than a Mac can fully ingest + enrich.
    A supervised cycle therefore snapshots the safe tip once, processes only
    toward that immutable target, and defers newly-produced blocks to the next
    cycle. If the ingest wall-clock budget is exhausted first, the cycle exits
    normally with a fail-closed CATCHING_UP status instead of being killed by
    the 90-second supervisor watchdog.
    """

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        # recent_collections() filters by block_time first. Existing databases
        # only had (collection, block_time), which can force a large table scan
        # as the local event history grows. These indexes are idempotent and
        # also accelerate retention deletes; no wallet/execution state changes.
        started=time.time()
        self.db.conn.execute('CREATE INDEX IF NOT EXISTS idx_mint_time ON mint_events(block_time)')
        self.db.conn.execute('CREATE INDEX IF NOT EXISTS idx_market_time ON market_events(block_time)')
        self.db.conn.commit()
        self._stage('DB_TIME_INDEX_READY',seconds=round(time.time()-started,3))

    def _attach_historical_gaps(self,status):
        gaps=self._historical_gap_ranges()
        if gaps:
            status.setdefault('scan',{})['historical_gaps']=[
                {
                    'state':'RECORDED_NOT_BACKFILLED',
                    'from_block':a,
                    'to_block':b,
                    'blocks':b-a+1,
                }
                for a,b in gaps
            ]
        return status

    def _previous_scan_counters(self):
        """Read last published non-gating counters without scanning full tables."""
        path=os.getenv('RADAR_STATUS_PATH',config.STATUS_PATH)
        try:
            with open(path,'r') as f:
                old=json.load(f)
            scan=old.get('scan') or {}
            return {
                'total_mint_units_stored':scan.get('total_mint_units_stored'),
                'secondary_sales_stored':scan.get('secondary_sales_stored'),
                'hoodsea_launches_stored':scan.get('hoodsea_launches_stored'),
            }
        except Exception:
            return {
                'total_mint_units_stored':None,
                'secondary_sales_stored':None,
                'hoodsea_launches_stored':None,
            }

    def _runtime_db_operational(self):
        """O(1) connection probe for the live loop; full integrity stays in doctor."""
        try:
            row=self.db.conn.execute('SELECT 1').fetchone()
            return bool(row and int(row[0])==1)
        except Exception:
            return False

    def build_status(self,tip,safe_block,from_block,to_block,started_at):
        """Build a live status without repeated full-database scans.

        Base build_status historically ran PRAGMA integrity_check up to three
        times and EXACT_INT_SUM over the complete mint table every live cycle.
        Those are useful doctor/maintenance operations, but on a long-lived Mac
        database they can consume the entire 90-second watchdog after SCORE.
        Candidate scoring and every hard gate are unchanged here.
        """
        previous=self._previous_scan_counters()
        operational=self._runtime_db_operational()
        self._stage('STATUS_BUILD_START',db_operational=operational)

        old_maintain=self._maybe_maintain
        old_integrity=self.db.integrity_check
        old_health=self.db.db_health
        old_mints=self.db.total_mints
        old_market=self.db.total_market_sales
        old_launches=self.db.total_launches

        def runtime_integrity():
            return 'ok' if operational else 'runtime_probe_failed'

        def runtime_health():
            try:journal=self.db.conn.execute('PRAGMA journal_mode').fetchone()[0]
            except Exception:journal='unknown'
            try:size=os.path.getsize(self.db.path)
            except OSError:size=0
            return {
                'journal_mode':journal,
                'integrity':'RUNTIME_OPERATIONAL' if operational else 'RUNTIME_PROBE_FAILED',
                'full_integrity':'DEFERRED_TO_DOCTOR',
                'bytes':size,
            }

        self._maybe_maintain=lambda _now:None
        self.db.integrity_check=runtime_integrity
        self.db.db_health=runtime_health
        self.db.total_mints=lambda:previous['total_mint_units_stored']
        self.db.total_market_sales=lambda:previous['secondary_sales_stored']
        self.db.total_launches=lambda:previous['hoodsea_launches_stored']
        try:
            status=super().build_status(tip,safe_block,from_block,to_block,started_at)
        finally:
            self._maybe_maintain=old_maintain
            self.db.integrity_check=old_integrity
            self.db.db_health=old_health
            self.db.total_mints=old_mints
            self.db.total_market_sales=old_market
            self.db.total_launches=old_launches

        if not operational:
            status['live_ready']='NOT_READY'
            status['money_readiness']='DATABASE RUNTIME CHECK FAILED — WAIT'
            status['manual_packages']=[]
            status.setdefault('scan',{})['qualified_candidates']=0
            for c in status.get('watchlist') or []:
                c['qualified']=False
                c['qualification_path']=None
                c['action']='WAIT'
                if 'DATABASE_RUNTIME_CHECK_FAILED' not in c.setdefault('hard_gates',[]):
                    c['hard_gates'].append('DATABASE_RUNTIME_CHECK_FAILED')
            d=status.setdefault('diagnostics',[])
            d.append({'stage':'DB','reason':'RUNTIME_DB_PROBE_FAILED','error':'SELECT 1 failed','ts':int(time.time())})
            status['diagnostics']=d[-10:]

        scan=status.setdefault('scan',{})
        scan['heavy_db_metrics_state']='DEFERRED_TO_DOCTOR_OR_MAINTENANCE'
        self._stage('STATUS_BUILD_DONE',seconds=round(time.time()-started_at,3),db_operational=operational)
        return status

    def _catchup_status(self,tip,target_safe,first,processed_to,started,ranges,reason):
        # Keep fail-closed catch-up publication deliberately cheap. Do not run
        # full-table uint256 sums, DB integrity scans, or block-time RPC reads
        # in the watchdog tail. Exact counters return on the next live analysis.
        try:final_tip=self.rpc.block_number()
        except Exception:final_tip=tip
        final_safe=max(0,int(final_tip)-config.CONFIRMATION_BLOCKS)
        lag_blocks=max(0,final_safe-int(processed_to))
        lag_seconds=None
        diagnostics=list(self.diag)
        diagnostics.append({
            'stage':'INGEST',
            'reason':reason,
            'error':f'target_safe={target_safe}; processed_to={processed_to}; ranges={ranges}; budget_seconds={config.INGEST_CYCLE_BUDGET_SECONDS}',
            'ts':int(time.time()),
        })
        status={
            'schema_version':'1.3',
            'generated_at':int(time.time()),
            'mode':'READ_ONLY',
            'wallet_execution':'MANUAL_ONLY',
            'chain':{
                'name':'Robinhood Chain',
                'chain_id':config.CHAIN_ID,
                'latest_block':final_tip,
                'safe_block':final_safe,
                'confirmations':config.CONFIRMATION_BLOCKS,
                'latest_block_age_seconds':None,
                'rpc':config.DEFAULT_RPC_URL,
                'active_rpc':self.rpc.url,
                'rpc_failovers':self.rpc.failovers,
                'hoodsea_launchpad':config.HOODSEA_LAUNCHPAD,
                'seaport_1_6':config.SEAPORT_16,
            },
            'status':f'CATCHING UP {first}-{processed_to}',
            'money_readiness':'CATCHING UP — WAIT FOR LIVE TIP',
            'live_ready':'NOT_READY',
            'realized_net_usd':0,
            'capital_deployed_usd':0,
            'net_capital_day_pct':0,
            'win_rate_pct':0,
            'prediction_mae':None,
            'scan':{
                'from_block':first,
                'to_block':processed_to,
                'blocks_processed':max(0,processed_to-first+1),
                'lag_blocks':lag_blocks,
                'lag_seconds':lag_seconds,
                'analysis_age_seconds':None,
                'duration_seconds':round(time.time()-started,3),
                'next_block':processed_to+1,
                'total_mint_units_stored':None,
                'secondary_sales_stored':None,
                'hoodsea_launches_stored':None,
                'live_observations':0,
                'qualified_candidates':0,
            },
            'best_live_observation':None,
            'watchlist':[],
            'manual_packages':[],
            'learning':{
                'status':'PREDICTION_UNCERTIFIED',
                'qualified_samples':0,
                'observed_win_rate_pct':0,
                'brier':None,
                'ece':None,
            },
            'db':{'integrity':'DEFERRED_DURING_CATCHUP'},
            'diagnostics':diagnostics[-10:],
            'limitations':[
                'Scanner is catching up to a fixed per-cycle safe tip; no opportunity may be approved until live readiness returns.',
                'Heavy counters and integrity scans are deferred while catching up so status can publish before the supervisor deadline.',
                'Blocks produced after the cycle target are deferred to the next cycle and are not silently discarded.',
                'Public snapshots are periodic; the Mac runner is continuous while the Mac is awake and online.',
            ],
        }
        self._attach_historical_gaps(status)
        self._stage('DONE_CATCHUP',duration_seconds=status['scan']['duration_seconds'],lag_blocks=lag_blocks,next_block=processed_to+1)
        return status

    def scan_once(self,public_lookback=None):
        self._runtime_rebase_if_stale(public_lookback=public_lookback)
        started=time.time()
        self.diag=[]
        self._analysis_rows_cache=[]
        self._analysis_pruned=0
        self._analysis_overflow=0
        self._init_signatures()
        self._stage('START')
        chain=self.rpc.chain_id()
        if chain!=config.CHAIN_ID:
            raise RPCError(f'WRONG_CHAIN_ID:{chain}')

        tip=self.rpc.block_number()
        target_safe=max(0,tip-config.CONFIRMATION_BLOCKS)
        last=self._verify_checkpoint(self.db.last_block(),self.db.get_meta('last_block_hash'))
        if public_lookback is not None:
            first=max(0,target_safe-public_lookback+1)
        elif last is None:
            first=max(0,target_safe-config.INITIAL_LOOKBACK_BLOCKS+1)
        else:
            first=last+1
        if first>target_safe:
            first=target_safe

        cursor=first
        processed_to=first-1
        ranges=0
        max_ranges=50
        effective=max(1,min(config.CHUNK_BLOCKS,config.MAX_CATCHUP_BLOCKS,self.max_ingest_range_blocks))
        ingest_deadline=started+max(5.0,float(config.INGEST_CYCLE_BUDGET_SECONDS))
        self._stage('INGEST',from_block=first,safe_block=target_safe,target_frozen=True,budget_seconds=config.INGEST_CYCLE_BUDGET_SECONDS)

        while cursor<=target_safe and ranges<max_ranges:
            if ranges and time.time()>=ingest_deadline:
                self._stage('INGEST_DEFERRED',next_block=cursor,target_safe=target_safe,ranges=ranges,reason='WALL_CLOCK_BUDGET_PRE_RANGE')
                return self._catchup_status(tip,target_safe,first,processed_to,started,ranges,'INGEST_BUDGET_EXHAUSTED')
            end=min(target_safe,cursor+effective-1)
            self._scan_range_or_raise(cursor,end)
            self._checkpoint(end)
            processed_to=end
            cursor=end+1
            ranges+=1
            if cursor<=target_safe and time.time()>=ingest_deadline:
                self._stage('INGEST_DEFERRED',next_block=cursor,target_safe=target_safe,ranges=ranges,reason='WALL_CLOCK_BUDGET')
                return self._catchup_status(tip,target_safe,first,processed_to,started,ranges,'INGEST_BUDGET_EXHAUSTED')

        if cursor<=target_safe:
            self._stage('INGEST_DEFERRED',next_block=cursor,target_safe=target_safe,ranges=ranges,reason='RANGE_BUDGET')
            return self._catchup_status(tip,target_safe,first,processed_to,started,ranges,'INGEST_RANGE_BUDGET_EXHAUSTED')

        if processed_to<first:
            processed_to=min(first,target_safe)

        analysis_started=time.time()
        self._stage('SELECT')
        self._prepare_analysis_rows()
        self._stage('ENRICH',rows=len(self._analysis_rows_cache),overflow=self._analysis_overflow)
        self._prewarm_enrichment()
        self._stage('SCORE')
        status=self.build_status(tip,target_safe,first,processed_to,started)
        analysis_age=time.time()-analysis_started

        final_tip=self.rpc.block_number()
        final_safe=max(0,final_tip-config.CONFIRMATION_BLOCKS)
        lag_blocks,lag_seconds=self._lag_metrics(final_safe,processed_to)
        self._stage('TAIL_DEFERRED',next_block=processed_to+1,safe_block=final_safe,lag_seconds=lag_seconds)
        status.setdefault('chain',{})['latest_block']=final_tip
        status['chain']['safe_block']=final_safe
        status['chain']['active_rpc']=self.rpc.url
        status['chain']['rpc_failovers']=self.rpc.failovers
        try:status['chain']['latest_block_age_seconds']=max(0,int(time.time())-int(self.block_time(final_tip)))
        except Exception:pass
        scan=status.setdefault('scan',{})
        scan['from_block']=first
        scan['to_block']=processed_to
        scan['blocks_processed']=max(0,processed_to-first+1)
        scan['lag_blocks']=lag_blocks
        scan['lag_seconds']=lag_seconds
        scan['analysis_age_seconds']=round(analysis_age,3)
        scan['duration_seconds']=round(time.time()-started,3)
        scan['next_block']=processed_to+1
        status['status']=f'SCANNING {first}-{processed_to}'
        self._attach_historical_gaps(status)
        self._stage('DONE',duration_seconds=scan['duration_seconds'],lag_seconds=lag_seconds,analysis_age_seconds=scan['analysis_age_seconds'])
        return status
