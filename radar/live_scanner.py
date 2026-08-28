import time
from concurrent.futures import ThreadPoolExecutor
from . import config
from .explorer import BlockscoutClient
from .rpc import RPCClient,RPCError
from .safety import evaluate_safety
from .scanner import RadarScanner as BaseRadarScanner,decode_string_word,data_word
from .signatures import TOPICS,SELECTORS


_CRITICAL_LOG_FAILURES={
    'ERC721_LOG_SCAN_FAILED',
    'ERC1155_SINGLE_SCAN_FAILED',
    'ERC1155_BATCH_SCAN_FAILED',
    'HOODSEA_LAUNCH_SCAN_FAILED',
    'HOODSEA_NFTSOLD_SCAN_FAILED',
    'SEAPORT_LOG_SCAN_FAILED',
}


class LiveRadarScanner(BaseRadarScanner):
    """Continuous scanner with durable ingest and bounded fail-closed enrichment."""

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._snapshot_cache={}
        self._ownership_cache={}
        self.enrich_rpc=RPCClient(config.DEFAULT_RPC_URL,timeout=4,retries=1)
        self.enrich_explorer=BlockscoutClient(config.BLOCKSCOUT_API,timeout=5,v2_base=config.BLOCKSCOUT_V2)
        def cached_ownership(address,total_supply=None):
            key=address.lower();now=time.time();cached=self._ownership_cache.get(key)
            if cached and now-cached[0] <= 60 and cached[1]==total_supply:return cached[2]
            value=self.enrich_explorer.ownership(address,total_supply);self._ownership_cache[key]=(now,total_supply,value);return value
        self.explorer.ownership=cached_ownership

    def _init_signatures(self):
        if self._topics:return
        self._topics=dict(TOPICS);self._selectors=dict(SELECTORS)

    def _e_uint(self,address,name):
        sel=self._selectors.get(name)
        if not sel:return None
        try:
            out=self.enrich_rpc.eth_call(address,sel);return int(out,16) if out and out!='0x' else None
        except Exception:return None
    def _e_address(self,address,name):
        sel=self._selectors.get(name)
        if not sel:return None
        try:
            out=self.enrich_rpc.eth_call(address,sel);return '0x'+out[-40:] if out and len(out)>=42 else None
        except Exception:return None
    def _e_string(self,address,name):
        sel=self._selectors.get(name)
        if not sel:return None
        try:return decode_string_word(self.enrich_rpc.eth_call(address,sel),0)
        except Exception:return None
    def _e_supports(self,address,interface_id):
        sel=self._selectors.get('supports')
        if not sel:return None
        try:
            data=sel+interface_id[2:].rjust(64,'0');out=self.enrich_rpc.eth_call(address,data);return bool(int(out,16)) if out and out!='0x' else False
        except Exception:return None

    def contract_snapshot(self,address):
        key=address.lower();now=time.time();cached=self._snapshot_cache.get(key)
        if cached and now-cached[0] <= 60:return cached[1]
        def get_code():
            try:return self.enrich_rpc.code(address)
            except Exception as exc:self._diag('CONTRACT_CHECK','GET_CODE_FAILED',exc);return None
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures={'code':pool.submit(get_code),'ver':pool.submit(self.enrich_explorer.verification,address),'total':pool.submit(self._e_uint,address,'totalSupply'),'minted':pool.submit(self._e_uint,address,'totalMinted'),'max':pool.submit(self._e_uint,address,'maxSupply'),'price_wei':pool.submit(self._e_uint,address,'mintPriceWei'),'price':pool.submit(self._e_uint,address,'mintPrice'),'name':pool.submit(self._e_string,address,'name'),'symbol':pool.submit(self._e_string,address,'symbol'),'owner':pool.submit(self._e_address,address,'owner'),'erc721':pool.submit(self._e_supports,address,'0x80ac58cd'),'erc1155':pool.submit(self._e_supports,address,'0xd9b67a26')}
            r={k:f.result() for k,f in futures.items()}
        ver=r['ver'] or {'verified':None,'source_text':'','review_risks':['VERIFICATION_UNAVAILABLE'],'hard_risks':[],'capabilities':[]};total=r['total'] if r['total'] is not None else r['minted'];price=r['price_wei'] if r['price_wei'] is not None else r['price'];cname=ver.get('contract_name') or '';is_hoodsea='hoodseanft' in cname.lower();snap_name=r['name'];snap_ticker=r['symbol']
        if is_hoodsea and self._selectors.get('info'):
            try:
                info=self.enrich_rpc.eth_call(address,self._selectors['info']);snap_name=snap_name or decode_string_word(info,0);snap_ticker=snap_ticker or decode_string_word(info,1)
                if price is None:price=data_word(info,8)
            except Exception:pass
        safety=evaluate_safety(ver,owner_address=r['owner']);code=r['code']
        if code in ('0x','0x0'):safety['state']='REJECT';safety['hard_risks']=sorted(set(safety.get('hard_risks',[])+['NO_CONTRACT_CODE']))
        elif code is None:
            if safety.get('state')=='PASS':safety['state']='REVIEW'
            safety['review_risks']=sorted(set(safety.get('review_risks',[])+['CONTRACT_CODE_UNAVAILABLE']))
        value={'safety':safety,'supply':{'total_supply':total,'max_supply':r['max']},'mint_price_wei':price,'name':snap_name,'ticker':snap_ticker,'is_hoodsea':is_hoodsea,'contract_name':cname,'source_text':ver.get('source_text') or '','interfaces':{'erc721':r['erc721'],'erc1155':r['erc1155']}};self._snapshot_cache[key]=(now,value);return value

    def _prewarm_enrichment(self):
        now=int(time.time());rows=self.db.recent_collections(now-3600)[:config.MAX_CANDIDATES*3];rows=rows[:max(config.MAX_CANDIDATES,8)]
        def warm(row):
            snap=self.contract_snapshot(row['collection']);self.explorer.ownership(row['collection'],snap['supply'].get('total_supply'))
        if rows:
            with ThreadPoolExecutor(max_workers=min(8,len(rows))) as pool:list(pool.map(warm,rows))

    def _scan_range_or_raise(self,from_block,to_block):
        before=len(self.diag);added=super().scan_logs(from_block,to_block);failures=[d for d in self.diag[before:] if d.get('reason') in _CRITICAL_LOG_FAILURES]
        if failures:raise RPCError(f"CRITICAL_LOG_SCAN_FAILED:{from_block}-{to_block}:{','.join(sorted({d.get('reason') for d in failures}))}")
        return added
    def _checkpoint(self,block_number):
        bh=(self.rpc.block(block_number) or {}).get('hash')
        if not bh:raise RPCError(f'CHECKPOINT_BLOCK_HASH_UNAVAILABLE:{block_number}')
        self.db.set_meta('last_block_hash',bh);self.db.set_meta('last_block',block_number)
    def _verify_checkpoint(self,last,stored_hash):
        if last is None or not stored_hash:return last
        live_hash=(self.rpc.block(last) or {}).get('hash')
        if not live_hash:raise RPCError(f'CHECKPOINT_HASH_VERIFY_UNAVAILABLE:{last}')
        if live_hash.lower()!=stored_hash.lower():
            self._diag('REORG','CHECKPOINT_HASH_MISMATCH',f'{last}');rewind=max(0,last-config.REORG_REWIND_BLOCKS);rewind_hash=(self.rpc.block(rewind) or {}).get('hash')
            if not rewind_hash:raise RPCError(f'REORG_REWIND_HASH_UNAVAILABLE:{rewind}')
            self.db.set_meta('last_block_hash',rewind_hash);self.db.set_meta('last_block',rewind);return rewind
        return last
    def _lag_metrics(self,safe_block,processed_to):
        if safe_block is None or processed_to is None:return None,None
        blocks=max(0,int(safe_block)-int(processed_to));safe_ts=self.block_time(int(safe_block));cursor_ts=self.block_time(int(processed_to));return blocks,max(0,int(safe_ts)-int(cursor_ts))
    def _lag_is_ready(self,blocks,seconds):return blocks is not None and seconds is not None and blocks<=config.MAX_READY_LAG_BLOCKS and seconds<=config.MAX_READY_LAG_SECONDS
    def _catch_up(self,cursor,safe,chunk,max_ranges):
        processed_to=cursor-1;ranges=0
        while cursor<=safe and ranges<max_ranges:
            end=min(safe,cursor+chunk-1);self._scan_range_or_raise(cursor,end);self._checkpoint(end);processed_to=end;cursor=end+1;ranges+=1
        return processed_to,ranges

    def scan_once(self,public_lookback=None):
        started=time.time();self.diag=[];self._init_signatures();chain=self.rpc.chain_id()
        if chain!=config.CHAIN_ID:raise RPCError(f'WRONG_CHAIN_ID:{chain}')
        tip=self.rpc.block_number();safe=max(0,tip-config.CONFIRMATION_BLOCKS);last=self._verify_checkpoint(self.db.last_block(),self.db.get_meta('last_block_hash'))
        if public_lookback is not None:first=max(0,safe-public_lookback+1)
        elif last is None:first=max(0,safe-config.INITIAL_LOOKBACK_BLOCKS+1)
        else:first=last+1
        if first>safe:first=safe
        cursor=first;processed_to=first-1;ranges=0;max_ranges=50;chunk=max(1,min(config.CHUNK_BLOCKS,config.MAX_CATCHUP_BLOCKS))
        while ranges<max_ranges:
            done,used=self._catch_up(cursor,safe,chunk,max_ranges-ranges)
            if done>=cursor:processed_to=done;cursor=done+1
            ranges+=used;tip=self.rpc.block_number();safe=max(0,tip-config.CONFIRMATION_BLOCKS);lag_blocks,lag_seconds=self._lag_metrics(safe,processed_to)
            if self._lag_is_ready(lag_blocks,lag_seconds):break
            cursor=processed_to+1
        if processed_to<first:processed_to=min(first,safe)
        analysis_started=time.time();self._prewarm_enrichment();status=self.build_status(tip,safe,first,processed_to,started);analysis_age=time.time()-analysis_started
        final_tip=self.rpc.block_number();final_safe=max(0,final_tip-config.CONFIRMATION_BLOCKS);tail_cursor=processed_to+1
        if tail_cursor<=final_safe:
            tail_done,_=self._catch_up(tail_cursor,final_safe,chunk,20)
            if tail_done>=tail_cursor:processed_to=tail_done
        final_tip=self.rpc.block_number();final_safe=max(0,final_tip-config.CONFIRMATION_BLOCKS);lag_blocks,lag_seconds=self._lag_metrics(final_safe,processed_to)
        status.setdefault('chain',{})['latest_block']=final_tip;status['chain']['safe_block']=final_safe
        try:status['chain']['latest_block_age_seconds']=max(0,int(time.time())-int(self.block_time(final_tip)))
        except Exception:pass
        scan=status.setdefault('scan',{});scan['from_block']=first;scan['to_block']=processed_to;scan['blocks_processed']=max(0,processed_to-first+1);scan['lag_blocks']=lag_blocks;scan['lag_seconds']=lag_seconds;scan['analysis_age_seconds']=round(analysis_age,3);scan['duration_seconds']=round(time.time()-started,3)
        status['status']=f'SCANNING {first}-{processed_to}'
        return status
