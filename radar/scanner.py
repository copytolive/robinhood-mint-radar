import json
import os
import time
from . import config
from .calibration import calibration_metrics,probability_from_score
from .db import RadarDB
from .explorer import BlockscoutClient
from .market import OpenSeaClient
from .relevance import evaluate_relevance
from .rpc import RPCClient,RPCError
from .safety import evaluate_safety
from .scoring import compute_metrics,score_candidate
from .seaport import decode_order_fulfilled,sale_records

def word_to_address(topic):
    if not topic or len(topic)<42:return None
    return '0x'+topic[-40:]
def uint_hex(x,default=None):
    try:return int(x,16)
    except Exception:return default
def _raw(data_hex):return bytes.fromhex(data_hex[2:] if (data_hex or '').startswith('0x') else (data_hex or ''))
def decode_string_word(data_hex,offset_word_index):
    try:
        raw=_raw(data_hex);base=32*offset_word_index;off=int.from_bytes(raw[base:base+32],'big');n=int.from_bytes(raw[off:off+32],'big');return raw[off+32:off+32+n].decode('utf-8','replace')
    except Exception:return None
def data_word(data_hex,index):
    try:return int.from_bytes(_raw(data_hex)[index*32:(index+1)*32],'big')
    except Exception:return None
def data_address(data_hex,index):
    try:
        word=_raw(data_hex)[index*32:(index+1)*32];return '0x'+word[-20:].hex() if len(word)==32 else None
    except Exception:return None
def decode_erc1155_single_quantity(data_hex):return data_word(data_hex,1) or 1
def decode_erc1155_single_token(data_hex):
    x=data_word(data_hex,0);return str(x) if x is not None else None
def decode_erc1155_batch(data_hex):
    try:
        raw=_raw(data_hex); ids_off=int.from_bytes(raw[0:32],'big');vals_off=int.from_bytes(raw[32:64],'big');ni=int.from_bytes(raw[ids_off:ids_off+32],'big');nv=int.from_bytes(raw[vals_off:vals_off+32],'big')
        if ni!=nv or ni>10000:return []
        ids=[int.from_bytes(raw[ids_off+32+i*32:ids_off+64+i*32],'big') for i in range(ni)];vals=[int.from_bytes(raw[vals_off+32+i*32:vals_off+64+i*32],'big') for i in range(nv)]
        return [(str(i),int(v)) for i,v in zip(ids,vals)]
    except Exception:return []

class RadarScanner:
    def __init__(self,db_path=None,rpc_url=None):
        self.db=RadarDB(db_path or config.DEFAULT_DB);self.rpc=RPCClient(rpc_url or config.DEFAULT_RPC_URL);self.explorer=BlockscoutClient(config.BLOCKSCOUT_API,v2_base=config.BLOCKSCOUT_V2);self.market=OpenSeaClient(config.OPENSea_API_KEY,config.OPENSEA_CHAIN);self._block_time={};self.diag=[];self._topics=None;self._selectors={};self._tx_cache={}
    def close(self):self.db.close()
    def _diag(self,stage,reason,error=None):self.diag.append({'stage':stage,'reason':reason,'error':str(error) if error else None,'ts':int(time.time())});self.diag=self.diag[-30:]
    def _init_signatures(self):
        if self._topics:return
        topics={'erc721':config.TRANSFER_TOPIC}
        for key,sig in {'erc1155_single':'TransferSingle(address,address,address,uint256,uint256)','erc1155_batch':'TransferBatch(address,address,address,uint256[],uint256[])','hoodsea_launch':'CollectionLaunched(address,address,string,string,uint256,uint256)','hoodsea_sold':'NFTSold(uint256,uint256,address,address)','seaport_fulfilled':'OrderFulfilled(bytes32,address,address,address,(uint8,address,uint256,uint256)[],(uint8,address,uint256,uint256,address)[])'}.items():
            try:topics[key]=self.rpc.sha3_text(sig)
            except Exception as exc:self._diag('SIGNATURES',f'{key.upper()}_TOPIC_UNAVAILABLE',exc)
        for name,sig in {'supports':'supportsInterface(bytes4)','totalSupply':'totalSupply()','totalMinted':'totalMinted()','maxSupply':'maxSupply()','mintPrice':'mintPrice()','mintPriceWei':'mintPriceWei()','name':'name()','symbol':'symbol()','info':'info()','owner':'owner()'}.items():
            try:self._selectors[name]=self.rpc.selector(sig)
            except Exception as exc:self._diag('SIGNATURES',f'{name.upper()}_SELECTOR_UNAVAILABLE',exc)
        self._topics=topics
    def block_time(self,n):
        if n not in self._block_time:
            b=self.rpc.block(n) or {};self._block_time[n]=uint_hex(b.get('timestamp'),int(time.time()))
        return self._block_time[n]
    def _log_base(self,log):
        bn=uint_hex(log.get('blockNumber'),0);li=uint_hex(log.get('logIndex'),0);tx=log.get('transactionHash') or '';return bn,li,tx,self.block_time(bn)
    def scan_logs(self,from_block,to_block):
        self._init_signatures();added=0
        try:
            for log in self.rpc.logs(from_block,to_block,[self._topics['erc721'],config.ZERO_TOPIC]):
                topics=log.get('topics') or []
                if len(topics)!=4:continue
                bn,li,tx,bt=self._log_base(log);self.db.add_mint({'event_id':f'{tx}:{li}','block_number':bn,'block_time':bt,'tx_hash':tx,'log_index':li,'collection':log['address'],'standard':'ERC721','recipient':word_to_address(topics[2]),'quantity':1,'token_id':str(uint_hex(topics[3],0)),'raw':log});added+=1
        except Exception as exc:self._diag('ERC721_SCAN','ERC721_LOG_SCAN_FAILED',exc)
        topic=self._topics.get('erc1155_single')
        if topic:
            try:
                for log in self.rpc.logs(from_block,to_block,[topic,None,config.ZERO_TOPIC]):
                    topics=log.get('topics') or []
                    if len(topics)<4:continue
                    bn,li,tx,bt=self._log_base(log);qty=decode_erc1155_single_quantity(log.get('data','0x'));tid=decode_erc1155_single_token(log.get('data','0x'));self.db.add_mint({'event_id':f'{tx}:{li}','block_number':bn,'block_time':bt,'tx_hash':tx,'log_index':li,'collection':log['address'],'standard':'ERC1155','recipient':word_to_address(topics[3]),'quantity':qty,'token_id':tid,'raw':log});added+=qty
            except Exception as exc:self._diag('ERC1155_SCAN','ERC1155_SINGLE_SCAN_FAILED',exc)
        topic=self._topics.get('erc1155_batch')
        if topic:
            try:
                for log in self.rpc.logs(from_block,to_block,[topic,None,config.ZERO_TOPIC]):
                    topics=log.get('topics') or []
                    if len(topics)<4:continue
                    bn,li,tx,bt=self._log_base(log);items=decode_erc1155_batch(log.get('data','0x'))
                    if not items:self._diag('ERC1155_SCAN','ERC1155_BATCH_DECODE_EMPTY',tx);continue
                    for idx,(tid,qty) in enumerate(items):self.db.add_mint({'event_id':f'{tx}:{li}:{idx}','block_number':bn,'block_time':bt,'tx_hash':tx,'log_index':li,'collection':log['address'],'standard':'ERC1155','recipient':word_to_address(topics[3]),'quantity':qty,'token_id':tid,'raw':log});added+=qty
            except Exception as exc:self._diag('ERC1155_SCAN','ERC1155_BATCH_SCAN_FAILED',exc)
        topic=self._topics.get('hoodsea_launch')
        if topic:
            try:
                for log in self.rpc.logs(from_block,to_block,[topic],address=config.HOODSEA_LAUNCHPAD):
                    topics=log.get('topics') or []
                    if len(topics)<3:continue
                    bn,li,tx,bt=self._log_base(log);data=log.get('data','0x');self.db.add_launch({'tx_hash':tx,'block_number':bn,'block_time':bt,'collection':word_to_address(topics[1]),'creator':word_to_address(topics[2]),'name':decode_string_word(data,0),'ticker':decode_string_word(data,1),'mint_price_wei':data_word(data,2),'mint_start':data_word(data,3),'raw':log})
            except Exception as exc:self._diag('HOODSEA_SCAN','HOODSEA_LAUNCH_SCAN_FAILED',exc)
        topic=self._topics.get('hoodsea_sold')
        if topic:
            try:
                for log in self.rpc.logs(from_block,to_block,[topic]):
                    topics=log.get('topics') or []
                    if len(topics)<2:continue
                    bn,li,tx,bt=self._log_base(log);data=log.get('data','0x');self.db.add_market_sale({'event_id':f'{tx}:{li}','block_number':bn,'block_time':bt,'tx_hash':tx,'log_index':li,'collection':log['address'],'event_type':'NFT_SOLD','token_id':str(uint_hex(topics[1],0)),'price_wei':data_word(data,0),'seller':data_address(data,1),'buyer':data_address(data,2),'source':'HOODSEA_NFTSOLD','raw':log})
            except Exception as exc:self._diag('HOODSEA_MARKET_SCAN','HOODSEA_NFTSOLD_SCAN_FAILED',exc)
        topic=self._topics.get('seaport_fulfilled')
        if topic:
            try:
                if self.rpc.code(config.SEAPORT_16) not in ('0x','0x0'):
                    for log in self.rpc.logs(from_block,to_block,[topic],address=config.SEAPORT_16):
                        bn,li,tx,bt=self._log_base(log)
                        try:
                            event=decode_order_fulfilled(log.get('data','0x'),log.get('topics') or [])
                            for idx,sale in enumerate(sale_records(event)):sale.update({'event_id':f'{tx}:{li}:{idx}','block_number':bn,'block_time':bt,'tx_hash':tx,'log_index':li,'event_type':'NFT_SOLD','raw':{'seaport':event.get('order_hash')}});self.db.add_market_sale(sale)
                        except Exception as dec_exc:self._diag('SEAPORT_DECODE','ORDER_FULFILLED_DECODE_FAILED',dec_exc)
            except Exception as exc:self._diag('SEAPORT_SCAN','SEAPORT_LOG_SCAN_FAILED',exc)
        return added
    def _call_uint(self,address,name):
        sel=self._selectors.get(name)
        if not sel:return None
        try:
            out=self.rpc.eth_call(address,sel);return int(out,16) if out and out!='0x' else None
        except Exception:return None
    def _call_address(self,address,name):
        sel=self._selectors.get(name)
        if not sel:return None
        try:
            out=self.rpc.eth_call(address,sel);return '0x'+out[-40:] if out and len(out)>=42 else None
        except Exception:return None
    def _call_string(self,address,name):
        sel=self._selectors.get(name)
        if not sel:return None
        try:return decode_string_word(self.rpc.eth_call(address,sel),0)
        except Exception:return None
    def _supports(self,address,interface_id):
        sel=self._selectors.get('supports')
        if not sel:return None
        try:
            data=sel+interface_id[2:].rjust(64,'0');out=self.rpc.eth_call(address,data);return bool(int(out,16)) if out and out!='0x' else False
        except Exception:return None
    def contract_snapshot(self,address):
        try:code=self.rpc.code(address)
        except Exception as exc:code='0x';self._diag('CONTRACT_CHECK','GET_CODE_FAILED',exc)
        ver=self.explorer.verification(address);total=self._call_uint(address,'totalSupply')
        if total is None:total=self._call_uint(address,'totalMinted')
        supply={'total_supply':total,'max_supply':self._call_uint(address,'maxSupply')};price=self._call_uint(address,'mintPriceWei')
        if price is None:price=self._call_uint(address,'mintPrice')
        cname=(ver.get('contract_name') or '');is_hoodsea='hoodseanft' in cname.lower();snap_name=self._call_string(address,'name');snap_ticker=self._call_string(address,'symbol')
        if is_hoodsea and self._selectors.get('info'):
            try:
                info=self.rpc.eth_call(address,self._selectors['info']);snap_name=snap_name or decode_string_word(info,0);snap_ticker=snap_ticker or decode_string_word(info,1)
                if price is None:price=data_word(info,8)
            except Exception:pass
        owner=self._call_address(address,'owner');safety=evaluate_safety(ver,owner_address=owner)
        if code in ('0x','0x0'):safety['state']='REJECT';safety['hard_risks']=sorted(set(safety.get('hard_risks',[])+['NO_CONTRACT_CODE']))
        return {'safety':safety,'supply':supply,'mint_price_wei':price,'name':snap_name,'ticker':snap_ticker,'is_hoodsea':is_hoodsea,'contract_name':cname,'source_text':ver.get('source_text') or '','interfaces':{'erc721':self._supports(address,'0x80ac58cd'),'erc1155':self._supports(address,'0xd9b67a26')}}
    def _observed_zero_price(self,events):
        for e in events[:3]:
            txh=e.get('tx_hash')
            if not txh:continue
            try:
                if txh not in self._tx_cache:self._tx_cache[txh]=self.rpc.transaction(txh) or {}
                tx=self._tx_cache[txh];value=uint_hex(tx.get('value'),None)
                if value==0:return 0,'OBSERVED_MINT_TX_VALUE_ZERO'
                if value is not None and value>0:return None,'OBSERVED_MINT_TX_VALUE_NONZERO_UNRESOLVED'
            except Exception:continue
        return None,None
    def _market_for(self,addr,snap,launch,now):
        market=self.market.collection_market(addr);onchain=self.db.market_summary(addr,now-86400)
        if onchain['sales_24h']>0:
            fb={'state':'LIVE','source':'+'.join(onchain['sources']),'sales_24h':onchain['sales_24h'],'native_sales_24h':onchain['native_sales_24h'],'volume_eth_24h':round(onchain['volume_eth_24h'],8),'floor_price':None,'reason':'ONCHAIN_SECONDARY_SALES_OBSERVED'}
            if market.get('state')!='LIVE':market=fb
            else:market['onchain_sales_24h']=onchain['sales_24h'];market['volume_eth_24h']=round(onchain['volume_eth_24h'],8);market['source']='OPENSEA_API+ONCHAIN'
        elif snap.get('is_hoodsea') and launch and market.get('state')!='LIVE':market={'state':'EARLY_ONCHAIN_ONLY','reason':'VERIFIED_HOODSEA_LAUNCH; NO_SECONDARY_SALE_OBSERVED_IN_LOCAL_24H_WINDOW','source':'HOODSEA_CONTRACT'}
        return market
    def _execution_surface(self,snap,launch,market):
        if snap.get('is_hoodsea') and launch:return {'state':'TRUSTED','url':config.HOODSEA_SITE,'source':'KNOWN_HOODSEA_LAUNCHPAD'}
        slug=market.get('slug')
        if slug:return {'state':'TRUSTED','url':f'https://opensea.io/collection/{slug}','source':'OPENSEA_INDEXED_COLLECTION'}
        return {'state':'UNAVAILABLE','url':None,'source':None}
    def _maybe_maintain(self,now):
        try:
            m=self.db.maintenance(now,config.OBSERVATION_RETENTION_DAYS,config.EVENT_RETENTION_DAYS)
            if m.get('integrity')!='ok':self._diag('DB','SQLITE_INTEGRITY_FAILED',m.get('integrity'))
            last=int(self.db.get_meta('last_backup','0') or 0)
            if not self.db.path.startswith('/tmp/') and now-last>=config.BACKUP_INTERVAL_SECONDS:path=self.db.backup(keep=config.BACKUP_KEEP);self.db.set_meta('last_backup',now);self._diag('DB','BACKUP_CREATED',path)
        except Exception as exc:self._diag('DB','MAINTENANCE_FAILED',exc)
    def _analysis_rows(self,rows,launches,now):
        """Hook for live scanners to cheaply prune rows before expensive enrichment."""
        return rows[:config.MAX_CANDIDATES*3]
    def build_status(self,tip,safe_block,from_block,to_block,started_at):
        now=int(time.time());self._maybe_maintain(now);launches=self.db.launches_map();rows=self.db.recent_collections(now-3600);candidates=[];filtered=0;analysis_rows=self._analysis_rows(rows,launches,now)
        for row in analysis_rows:
            addr=row['collection'];launch=launches.get(addr.lower());snap=self.contract_snapshot(addr);events=self.db.mint_window(addr,now-3600);price_wei=snap['mint_price_wei'];price_source='CONTRACT'
            if launch and launch.get('mint_price_wei') is not None:
                try:price_wei=int(launch['mint_price_wei']);price_source='HOODSEA_LAUNCH_EVENT'
                except Exception:pass
            if price_wei is None:
                inferred,src=self._observed_zero_price(events)
                if inferred is not None:price_wei=inferred;price_source=src
                elif src:price_source=src
            price_eth=price_wei/1e18 if price_wei is not None else None;metrics=compute_metrics(events,now);market=self._market_for(addr,snap,launch,now);relevance=evaluate_relevance(row['standard'],snap.get('contract_name') or snap.get('name'),snap.get('source_text',''),launch=launch,market=market,interfaces=snap.get('interfaces'))
            if relevance.get('state')=='REJECT':filtered+=1;continue
            ownership=self.explorer.ownership(addr,snap['supply'].get('total_supply'));execution=self._execution_surface(snap,launch,market);scored=score_candidate(price_eth,metrics,snap['supply'],snap['safety'],market,relevance=relevance,is_hoodsea=snap.get('is_hoodsea',False),launch=bool(launch),ownership=ownership,execution=execution)
            c={'collection':addr,'standard':row['standard'],'name':(launch or {}).get('name') or snap.get('name'),'ticker':(launch or {}).get('ticker') or snap.get('ticker'),'mint_price_eth':price_eth,'mint_price_source':price_source,'metrics':metrics,'supply':snap['supply'],'ownership':ownership,'relevance':relevance,'safety':snap['safety'],'market':market,'execution':execution,'score':scored['score'],'predicted_probability':probability_from_score(scored['score']),'score_parts':scored['parts'],'sell_through':scored['sell_through'],'hard_gates':scored['hard_gates'],'qualified':scored['qualified'],'qualification_path':scored.get('qualification_path'),'action':scored['action'],'explorer_url':f'https://robinhoodchain.blockscout.com/address/{addr}','opensea_url':f'https://opensea.io/assets/robinhood/{addr}'}
            candidates.append(c);self.db.add_observation(addr,c);self.db.observe_shadow(c,now)
            if len(candidates)>=config.MAX_CANDIDATES:break
        candidates.sort(key=lambda x:(x['qualified'],x['score'],x['metrics']['velocity_1m']),reverse=True);qualified=sum(1 for c in candidates if c['qualified']);outcomes=self.db.outcome_stats();shadow=self.db.shadow_stats();cal=calibration_metrics(self.db.calibration_samples());latest_time=self.block_time(tip) if tip else now;age=max(0,now-latest_time);fresh=age<=120
        if not fresh:self._diag('LIVE_DOCTOR','CHAIN_DATA_STALE',f'{age}s')
        readiness='READY' if fresh and self.db.integrity_check()=='ok' else 'NOT_READY';db_health=self.db.db_health()
        return {'schema_version':'1.3','generated_at':now,'mode':'READ_ONLY','wallet_execution':'MANUAL_ONLY','chain':{'name':'Robinhood Chain','chain_id':config.CHAIN_ID,'latest_block':tip,'safe_block':safe_block,'confirmations':config.CONFIRMATION_BLOCKS,'latest_block_age_seconds':age,'rpc':config.DEFAULT_RPC_URL,'hoodsea_launchpad':config.HOODSEA_LAUNCHPAD,'seaport_1_6':config.SEAPORT_16},'status':f'SCANNING {from_block}-{to_block}','money_readiness':'QUALIFIED OPPORTUNITY AVAILABLE' if qualified else 'WAIT FOR QUALIFIED OPPORTUNITY','live_ready':readiness,'realized_net_usd':round(outcomes['realized_net_usd'],4),'capital_deployed_usd':round(outcomes['capital_deployed_usd'],4),'net_capital_day_pct':round(outcomes['net_capital_day_pct'],4),'win_rate_pct':round(outcomes['win_rate_pct'],2),'prediction_mae':cal.get('mae'),'scan':{'from_block':from_block,'to_block':to_block,'blocks_processed':max(0,to_block-from_block+1),'total_mint_units_stored':self.db.total_mints(),'secondary_sales_stored':self.db.total_market_sales(),'hoodsea_launches_stored':self.db.total_launches(),'irrelevant_filtered':filtered,'analysis_rows_considered':len(analysis_rows),'live_observations':len(candidates),'qualified_candidates':qualified,'duration_seconds':round(time.time()-started_at,3)},'best_live_observation':candidates[0] if candidates else None,'watchlist':candidates[:10],'manual_packages':[c for c in candidates if c['qualified']][:5],'learning':{'status':cal['status'],'qualified_samples':outcomes['samples'],'observed_win_rate_pct':round(outcomes['win_rate_pct'],2),'brier':cal['brier'],'ece':cal['ece'],'calibration_samples':cal['samples'],'calibration_curve':cal['buckets'],'shadow':shadow},'db':db_health,'diagnostics':self.diag[-10:],'limitations':['Static contract safety analysis is conservative but is not a formal audit or guarantee.','On-chain Seaport evidence removes the OpenSea API-key dependency for observed sales; floor/offer enrichment still benefits from the official OpenSea API.','Blockscout holder data is used when available; API unavailability is surfaced explicitly.','A zero transaction value is only used as a conservative free-mint observation; non-zero transaction value is not assumed to equal unit mint price.','Prediction calibration remains uncertified until enough realized or matured shadow outcomes exist.','Public snapshots are periodic; the Mac runner is continuous while the Mac is awake and online.']}
    def scan_once(self,public_lookback=None):
        started=time.time();self.diag=[];self._init_signatures();chain=self.rpc.chain_id()
        if chain!=config.CHAIN_ID:raise RPCError(f'WRONG_CHAIN_ID:{chain}')
        tip=self.rpc.block_number();safe=max(0,tip-config.CONFIRMATION_BLOCKS);last=self.db.last_block();stored_hash=self.db.get_meta('last_block_hash')
        if last is not None and stored_hash:
            try:
                live_hash=(self.rpc.block(last) or {}).get('hash')
                if live_hash and live_hash.lower()!=stored_hash.lower():self._diag('REORG','CHECKPOINT_HASH_MISMATCH',f'{last}');last=max(0,last-config.REORG_REWIND_BLOCKS);self.db.set_meta('last_block',last)
            except Exception as exc:self._diag('REORG','CHECKPOINT_HASH_VERIFY_FAILED',exc)
        if public_lookback is not None:from_block=max(0,safe-public_lookback+1);to_block=safe
        elif last is None:from_block=max(0,safe-config.INITIAL_LOOKBACK_BLOCKS+1);to_block=safe
        else:
            from_block=last+1;to_block=min(safe,from_block+config.CHUNK_BLOCKS-1)
            if from_block>safe:from_block=to_block=safe
        self.scan_logs(from_block,to_block);self.db.set_meta('last_block',to_block);bh=(self.rpc.block(to_block) or {}).get('hash')
        if bh:self.db.set_meta('last_block_hash',bh)
        return self.build_status(tip,safe,from_block,to_block,started)

def write_status(path,status):
    os.makedirs(os.path.dirname(path) or '.',exist_ok=True);tmp=path+'.tmp'
    with open(tmp,'w') as f:json.dump(status,f,indent=2,sort_keys=True)
    os.replace(tmp,path,status)