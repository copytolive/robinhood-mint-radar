import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

from . import config
from .live_scanner import LiveRadarScanner
from .rpc import RPCClient,RPCError
from .scanner import (
    data_address,
    data_word,
    decode_erc1155_batch,
    decode_erc1155_single_quantity,
    decode_erc1155_single_token,
    decode_string_word,
    uint_hex,
    word_to_address,
)
from .seaport import decode_order_fulfilled,sale_records


class FastLiveRadarScanner(LiveRadarScanner):
    """Live scanner whose ingest path is bounded for high-block-rate chains.

    The normal scanner semantics remain unchanged: every successful range is
    checkpointed in order and any failed critical log family aborts the range.
    Only network scheduling changes: log families are fetched in one JSON-RPC
    batch when possible, block timestamps are batch-prefetched, and SQLite
    writes remain serialized on the scanner thread.
    """

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        primary=kwargs.get('rpc_url') or config.DEFAULT_RPC_URL
        self.ingest_rpc=RPCClient(
            primary,
            timeout=float(os.getenv('RADAR_INGEST_RPC_TIMEOUT','3')),
            retries=0,
            fallback_urls=config.RPC_FALLBACK_URLS,
            expected_chain_id=config.CHAIN_ID,
        )
        self.max_ingest_range_blocks=max(16,int(os.getenv('RADAR_MAX_INGEST_RANGE_BLOCKS','128')))

    def _prewarm_enrichment(self):
        """Warm bounded candidate network data concurrently, never SQLite from workers."""
        rows=self._analysis_rows_cache or self._prepare_analysis_rows()
        if not rows or not hasattr(self.db,'mint_window'):return
        now=int(time.time())
        prepared=[(row,self.db.mint_window(row['collection'],now-3600)) for row in rows]

        def warm(item):
            row,events=item
            snap=self.contract_snapshot(row['collection'])
            try:self.explorer.ownership(row['collection'],snap.get('supply',{}).get('total_supply'))
            except Exception:pass
            self._observed_zero_price(events)

        workers=max(1,min(len(prepared),int(config.MAX_ANALYSIS_ROWS),4))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(warm,prepared))

    def _query_specs(self,from_block,to_block):
        self._init_signatures()
        specs=[]
        def add(name,topics,address=None):
            if not topics or not topics[0]:return
            q={'fromBlock':hex(from_block),'toBlock':hex(to_block),'topics':topics}
            if address:q['address']=address
            specs.append((name,topics,address,q))
        add('erc721',[self._topics.get('erc721'),config.ZERO_TOPIC])
        add('erc1155_single',[self._topics.get('erc1155_single'),None,config.ZERO_TOPIC])
        add('erc1155_batch',[self._topics.get('erc1155_batch'),None,config.ZERO_TOPIC])
        add('hoodsea_launch',[self._topics.get('hoodsea_launch')],config.HOODSEA_LAUNCHPAD)
        add('hoodsea_sold',[self._topics.get('hoodsea_sold')])
        add('seaport_fulfilled',[self._topics.get('seaport_fulfilled')],config.SEAPORT_16)
        return specs

    def _fetch_log_families(self,from_block,to_block):
        specs=self._query_specs(from_block,to_block)
        if not specs:return {}
        try:
            rows=self.ingest_rpc.batch_call([('eth_getLogs',[q]) for _name,_topics,_address,q in specs])
            return {spec[0]:(rows[i] or []) for i,spec in enumerate(specs)}
        except Exception as batch_exc:
            self._stage('INGEST_BATCH_FALLBACK',from_block=from_block,to_block=to_block,error=str(batch_exc)[:240])

        def fetch(spec):
            name,topics,address,_q=spec
            try:return name,self.ingest_rpc.logs(from_block,to_block,topics,address)
            except Exception as exc:raise RPCError(f'{name.upper()}_LOG_SCAN_FAILED:{from_block}-{to_block}:{exc}') from exc

        workers=max(1,min(6,len(specs)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pairs=list(pool.map(fetch,specs))
        return {name:(rows or []) for name,rows in pairs}

    def _prefetch_block_times(self,families):
        missing=sorted({
            uint_hex(log.get('blockNumber'),0)
            for rows in families.values()
            for log in rows
            if uint_hex(log.get('blockNumber'),0) not in self._block_time
        })
        missing=[n for n in missing if n>0]
        if not missing:return 0
        blocks=self.ingest_rpc.blocks(missing,batch_size=64,max_workers=16)
        for n in missing:
            block=blocks.get(n) or {};ts=uint_hex(block.get('timestamp'),None)
            if ts is None:raise RPCError(f'BLOCK_TIMESTAMP_UNAVAILABLE:{n}')
            self._block_time[n]=ts
        return len(missing)

    def _cached_log_base(self,log):
        bn=uint_hex(log.get('blockNumber'),0);li=uint_hex(log.get('logIndex'),0);tx=log.get('transactionHash') or ''
        bt=self._block_time.get(bn)
        if bt is None:raise RPCError(f'BLOCK_TIMESTAMP_NOT_PREFETCHED:{bn}')
        return bn,li,tx,bt

    def _commit_families(self,families):
        added=0
        for log in families.get('erc721',[]):
            topics=log.get('topics') or []
            if len(topics)!=4:continue
            bn,li,tx,bt=self._cached_log_base(log)
            self.db.add_mint({'event_id':f'{tx}:{li}','block_number':bn,'block_time':bt,'tx_hash':tx,'log_index':li,'collection':log['address'],'standard':'ERC721','recipient':word_to_address(topics[2]),'quantity':1,'token_id':str(uint_hex(topics[3],0)),'raw':log});added+=1

        for log in families.get('erc1155_single',[]):
            topics=log.get('topics') or []
            if len(topics)<4:continue
            bn,li,tx,bt=self._cached_log_base(log);qty=decode_erc1155_single_quantity(log.get('data','0x'));tid=decode_erc1155_single_token(log.get('data','0x'))
            self.db.add_mint({'event_id':f'{tx}:{li}','block_number':bn,'block_time':bt,'tx_hash':tx,'log_index':li,'collection':log['address'],'standard':'ERC1155','recipient':word_to_address(topics[3]),'quantity':qty,'token_id':tid,'raw':log});added+=qty

        for log in families.get('erc1155_batch',[]):
            topics=log.get('topics') or []
            if len(topics)<4:continue
            bn,li,tx,bt=self._cached_log_base(log);items=decode_erc1155_batch(log.get('data','0x'))
            if not items:self._diag('ERC1155_SCAN','ERC1155_BATCH_DECODE_EMPTY',tx);continue
            for idx,(tid,qty) in enumerate(items):
                self.db.add_mint({'event_id':f'{tx}:{li}:{idx}','block_number':bn,'block_time':bt,'tx_hash':tx,'log_index':li,'collection':log['address'],'standard':'ERC1155','recipient':word_to_address(topics[3]),'quantity':qty,'token_id':tid,'raw':log});added+=qty

        for log in families.get('hoodsea_launch',[]):
            topics=log.get('topics') or []
            if len(topics)<3:continue
            bn,li,tx,bt=self._cached_log_base(log);data=log.get('data','0x')
            self.db.add_launch({'tx_hash':tx,'block_number':bn,'block_time':bt,'collection':word_to_address(topics[1]),'creator':word_to_address(topics[2]),'name':decode_string_word(data,0),'ticker':decode_string_word(data,1),'mint_price_wei':data_word(data,2),'mint_start':data_word(data,3),'raw':log})

        for log in families.get('hoodsea_sold',[]):
            topics=log.get('topics') or []
            if len(topics)<2:continue
            bn,li,tx,bt=self._cached_log_base(log);data=log.get('data','0x')
            self.db.add_market_sale({'event_id':f'{tx}:{li}','block_number':bn,'block_time':bt,'tx_hash':tx,'log_index':li,'collection':log['address'],'event_type':'NFT_SOLD','token_id':str(uint_hex(topics[1],0)),'price_wei':data_word(data,0),'seller':data_address(data,1),'buyer':data_address(data,2),'source':'HOODSEA_NFTSOLD','raw':log})

        for log in families.get('seaport_fulfilled',[]):
            bn,li,tx,bt=self._cached_log_base(log)
            try:
                event=decode_order_fulfilled(log.get('data','0x'),log.get('topics') or [])
                for idx,sale in enumerate(sale_records(event)):
                    sale.update({'event_id':f'{tx}:{li}:{idx}','block_number':bn,'block_time':bt,'tx_hash':tx,'log_index':li,'event_type':'NFT_SOLD','raw':{'seaport':event.get('order_hash')}});self.db.add_market_sale(sale)
            except Exception as dec_exc:self._diag('SEAPORT_DECODE','ORDER_FULFILLED_DECODE_FAILED',dec_exc)
        return added

    def _scan_range_or_raise(self,from_block,to_block):
        started=time.time();self._stage('INGEST_RANGE',from_block=from_block,to_block=to_block)
        families=self._fetch_log_families(from_block,to_block);fetch_seconds=time.time()-started
        counts={name:len(rows) for name,rows in families.items()};self._stage('INGEST_FETCHED',from_block=from_block,to_block=to_block,seconds=round(fetch_seconds,3),counts=counts)
        ts_started=time.time();timestamp_blocks=self._prefetch_block_times(families);self._stage('INGEST_TIMESTAMPS',blocks=timestamp_blocks,seconds=round(time.time()-ts_started,3))
        commit_started=time.time();added=self._commit_families(families);self._stage('INGEST_COMMIT',added=added,seconds=round(time.time()-commit_started,3),total_seconds=round(time.time()-started,3))
        return added

    def _catch_up(self,cursor,safe,chunk,max_ranges):
        effective=max(1,min(int(chunk),self.max_ingest_range_blocks));processed_to=cursor-1;ranges=0
        while cursor<=safe and ranges<max_ranges:
            end=min(safe,cursor+effective-1);self._scan_range_or_raise(cursor,end);self._checkpoint(end);processed_to=end;cursor=end+1;ranges+=1
        return processed_to,ranges

    def _historical_gap_ranges(self):
        ranges=[]
        raw=self.db.get_meta('historical_gaps_json')
        if raw:
            try:
                for item in json.loads(raw):
                    if isinstance(item,(list,tuple)) and len(item)==2:
                        ranges.append((int(item[0]),int(item[1])))
            except Exception:
                pass
        legacy_from=self.db.get_meta('historical_gap_from');legacy_to=self.db.get_meta('historical_gap_to')
        if legacy_from is not None and legacy_to is not None:
            try:ranges.append((int(legacy_from),int(legacy_to)))
            except (TypeError,ValueError):pass
        normalized=[]
        for start,end in sorted(ranges):
            if end<start:continue
            if normalized and start<=normalized[-1][1]+1:
                normalized[-1]=(normalized[-1][0],max(normalized[-1][1],end))
            else:normalized.append((start,end))
        return normalized

    def _record_historical_gap(self,start,end):
        start=int(start);end=int(end)
        if end<start:return
        ranges=self._historical_gap_ranges();ranges.append((start,end));normalized=[]
        for a,b in sorted(ranges):
            if normalized and a<=normalized[-1][1]+1:normalized[-1]=(normalized[-1][0],max(normalized[-1][1],b))
            else:normalized.append((a,b))
        self.db.set_meta('historical_gaps_json',json.dumps([[a,b] for a,b in normalized],separators=(',',':')))

    def _runtime_rebase_if_stale(self,public_lookback=None):
        if public_lookback is not None:return
        last=self.db.last_block()
        if last is None:return
        tip=self.rpc.block_number();safe=max(0,tip-config.CONFIRMATION_BLOCKS);lag=max(0,safe-int(last))
        threshold=max(int(config.RUNTIME_REBASE_LAG_BLOCKS),int(config.INITIAL_LOOKBACK_BLOCKS))
        lag_seconds=None
        try:
            safe_ts=self.block_time(safe);last_ts=self.block_time(int(last));lag_seconds=max(0,int(safe_ts)-int(last_ts))
        except Exception:
            pass
        stale_blocks=lag>threshold
        stale_time=lag_seconds is not None and lag_seconds>int(config.RUNTIME_REBASE_LAG_SECONDS)
        if not stale_blocks and not stale_time:return
        new_first=max(0,safe-config.INITIAL_LOOKBACK_BLOCKS+1);checkpoint=max(0,new_first-1)
        gap_from=int(last)+1;gap_to=checkpoint
        if gap_to>=gap_from:self._record_historical_gap(gap_from,gap_to)
        block=self.rpc.block(checkpoint) or {};block_hash=block.get('hash')
        if not block_hash:raise RPCError(f'RUNTIME_REBASE_HASH_UNAVAILABLE:{checkpoint}')
        self.db.set_meta('last_block_hash',block_hash);self.db.set_meta('last_block',checkpoint)
        detail=f'lag_blocks={lag}; lag_seconds={lag_seconds}; gap={gap_from}-{gap_to}; resume={new_first}'
        self._diag('LIVE_RECOVERY','RUNTIME_CURSOR_REBASED',detail)
        self._stage('RUNTIME_REBASE',lag_blocks=lag,lag_seconds=lag_seconds,gap_from=gap_from,gap_to=gap_to,resume_from=new_first)

    def scan_once(self,public_lookback=None):
        self._runtime_rebase_if_stale(public_lookback=public_lookback)
        status=super().scan_once(public_lookback=public_lookback)
        gaps=self._historical_gap_ranges()
        if gaps:
            status.setdefault('scan',{})['historical_gaps']=[
                {'state':'RECORDED_NOT_BACKFILLED','from_block':a,'to_block':b,'blocks':b-a+1}
                for a,b in gaps
            ]
        return status