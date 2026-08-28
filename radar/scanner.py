import json
import os
import time
from collections import defaultdict
from . import config
from .db import RadarDB
from .explorer import BlockscoutClient
from .market import OpenSeaClient
from .rpc import RPCClient, RPCError
from .scoring import compute_metrics, score_candidate


def word_to_address(topic):
    if not topic or len(topic)<42: return None
    return '0x'+topic[-40:]

def uint_hex(x, default=None):
    try: return int(x,16)
    except Exception: return default

def decode_string_word(data_hex, offset_word_index):
    try:
        raw=bytes.fromhex(data_hex[2:] if data_hex.startswith('0x') else data_hex)
        base=32*offset_word_index
        off=int.from_bytes(raw[base:base+32],'big')
        n=int.from_bytes(raw[off:off+32],'big')
        return raw[off+32:off+32+n].decode('utf-8','replace')
    except Exception:
        return None

def data_word(data_hex,index):
    try:
        raw=bytes.fromhex(data_hex[2:] if data_hex.startswith('0x') else data_hex)
        return int.from_bytes(raw[index*32:(index+1)*32],'big')
    except Exception:
        return None

def data_address(data_hex,index):
    try:
        raw=bytes.fromhex(data_hex[2:] if data_hex.startswith('0x') else data_hex)
        word=raw[index*32:(index+1)*32]
        return '0x'+word[-20:].hex() if len(word)==32 else None
    except Exception:
        return None

def decode_erc1155_single_quantity(data_hex):
    return data_word(data_hex,1) or 1

def decode_erc1155_single_token(data_hex):
    x=data_word(data_hex,0)
    return str(x) if x is not None else None

class RadarScanner:
    def __init__(self, db_path=None, rpc_url=None):
        self.db=RadarDB(db_path or config.DEFAULT_DB)
        self.rpc=RPCClient(rpc_url or config.DEFAULT_RPC_URL)
        self.explorer=BlockscoutClient(config.BLOCKSCOUT_API)
        self.market=OpenSeaClient(config.OPENSea_API_KEY,config.OPENSEA_CHAIN)
        self._block_time={}
        self.diag=[]
        self._topics=None
        self._selectors={}

    def close(self): self.db.close()

    def _diag(self,stage,reason,error=None):
        self.diag.append({'stage':stage,'reason':reason,'error':str(error) if error else None,'ts':int(time.time())})
        self.diag=self.diag[-20:]

    def _init_signatures(self):
        if self._topics: return
        topics={'erc721':config.TRANSFER_TOPIC}
        for key,sig in {
          'erc1155_single':'TransferSingle(address,address,address,uint256,uint256)',
          'erc1155_batch':'TransferBatch(address,address,address,uint256[],uint256[])',
          'hoodsea_launch':'CollectionLaunched(address,address,string,string,uint256,uint256)',
          'hoodsea_sold':'NFTSold(uint256,uint256,address,address)'
        }.items():
            try: topics[key]=self.rpc.sha3_text(sig)
            except Exception as exc: self._diag('SIGNATURES',f'{key.upper()}_TOPIC_UNAVAILABLE',exc)
        for name,sig in {'supports':'supportsInterface(bytes4)','totalSupply':'totalSupply()','totalMinted':'totalMinted()','maxSupply':'maxSupply()','mintPrice':'mintPrice()','mintPriceWei':'mintPriceWei()','name':'name()','symbol':'symbol()','info':'info()'}.items():
            try:self._selectors[name]=self.rpc.selector(sig)
            except Exception as exc:self._diag('SIGNATURES',f'{name.upper()}_SELECTOR_UNAVAILABLE',exc)
        self._topics=topics

    def block_time(self,n):
        if n not in self._block_time:
            b=self.rpc.block(n) or {}
            self._block_time[n]=uint_hex(b.get('timestamp'),int(time.time()))
        return self._block_time[n]

    def _log_base(self,log):
        bn=uint_hex(log.get('blockNumber'),0)
        li=uint_hex(log.get('logIndex'),0)
        tx=log.get('transactionHash') or ''
        return bn,li,tx,self.block_time(bn)

    def scan_logs(self,from_block,to_block):
        self._init_signatures()
        added=0
        try:
            for log in self.rpc.logs(from_block,to_block,[self._topics['erc721'],config.ZERO_TOPIC]):
                topics=log.get('topics') or []
                if len(topics)!=4: continue
                bn,li,tx,bt=self._log_base(log)
                x={'event_id':f'{tx}:{li}','block_number':bn,'block_time':bt,'tx_hash':tx,'log_index':li,'collection':log['address'],'standard':'ERC721','recipient':word_to_address(topics[2]),'quantity':1,'token_id':str(uint_hex(topics[3],0)),'raw':log}
                self.db.add_mint(x); added+=1
        except Exception as exc:self._diag('ERC721_SCAN','ERC721_LOG_SCAN_FAILED',exc)
        for kind,standard in [('erc1155_single','ERC1155'),('erc1155_batch','ERC1155')]:
            topic=self._topics.get(kind)
            if not topic: continue
            try:
                for log in self.rpc.logs(from_block,to_block,[topic,None,config.ZERO_TOPIC]):
                    topics=log.get('topics') or []
                    if len(topics)<4: continue
                    bn,li,tx,bt=self._log_base(log)
                    qty=decode_erc1155_single_quantity(log.get('data','0x')) if kind=='erc1155_single' else 1
                    tid=decode_erc1155_single_token(log.get('data','0x')) if kind=='erc1155_single' else 'BATCH'
                    x={'event_id':f'{tx}:{li}','block_number':bn,'block_time':bt,'tx_hash':tx,'log_index':li,'collection':log['address'],'standard':standard,'recipient':word_to_address(topics[3]),'quantity':qty,'token_id':tid,'raw':log}
                    self.db.add_mint(x); added+=1
            except Exception as exc:self._diag('ERC1155_SCAN',f'{kind.upper()}_SCAN_FAILED',exc)
        topic=self._topics.get('hoodsea_launch')
        if topic:
            try:
                for log in self.rpc.logs(from_block,to_block,[topic],address=config.HOODSEA_LAUNCHPAD):
                    topics=log.get('topics') or []
                    if len(topics)<3: continue
                    bn,li,tx,bt=self._log_base(log)
                    data=log.get('data','0x')
                    x={'tx_hash':tx,'block_number':bn,'block_time':bt,'collection':word_to_address(topics[1]),'creator':word_to_address(topics[2]),'name':decode_string_word(data,0),'ticker':decode_string_word(data,1),'mint_price_wei':data_word(data,2),'mint_start':data_word(data,3),'raw':log}
                    self.db.add_launch(x)
            except Exception as exc:self._diag('HOODSEA_SCAN','HOODSEA_LAUNCH_SCAN_FAILED',exc)
        topic=self._topics.get('hoodsea_sold')
        if topic:
            try:
                for log in self.rpc.logs(from_block,to_block,[topic]):
                    topics=log.get('topics') or []
                    if len(topics)<2: continue
                    bn,li,tx,bt=self._log_base(log)
                    data=log.get('data','0x')
                    self.db.add_market_sale({'event_id':f'{tx}:{li}','block_number':bn,'block_time':bt,'tx_hash':tx,'log_index':li,'collection':log['address'],'event_type':'NFT_SOLD','token_id':str(uint_hex(topics[1],0)),'price_wei':data_word(data,0),'seller':data_address(data,1),'buyer':data_address(data,2),'raw':log})
            except Exception as exc:self._diag('HOODSEA_MARKET_SCAN','HOODSEA_NFTSOLD_SCAN_FAILED',exc)
        return added

    def _call_uint(self,address,name):
        sel=self._selectors.get(name)
        if not sel:return None
        try:
            out=self.rpc.eth_call(address,sel)
            return int(out,16) if out and out!='0x' else None
        except Exception:return None

    def contract_snapshot(self,address):
        code='0x'
        try: code=self.rpc.code(address)
        except Exception as exc:self._diag('CONTRACT_CHECK','GET_CODE_FAILED',exc)
        ver=self.explorer.verification(address)
        suspicious=list(ver.get('suspicious') or [])
        safety_state='PASS'
        if code in ('0x','0x0'): safety_state='REJECT'; suspicious.append('NO_CONTRACT_CODE')
        elif ver.get('verified') is False: safety_state='REJECT'
        elif ver.get('verified') is None: safety_state='REVIEW'
        elif suspicious: safety_state='REVIEW'
        total=self._call_uint(address,'totalSupply')
        if total is None: total=self._call_uint(address,'totalMinted')
        supply={'total_supply':total,'max_supply':self._call_uint(address,'maxSupply')}
        price=self._call_uint(address,'mintPriceWei')
        if price is None: price=self._call_uint(address,'mintPrice')
        cname=(ver.get('contract_name') or '')
        is_hoodsea='hoodseanft' in cname.lower()
        snap_name=None; snap_ticker=None
        if is_hoodsea and self._selectors.get('info'):
            try:
                info=self.rpc.eth_call(address,self._selectors['info'])
                snap_name=decode_string_word(info,0); snap_ticker=decode_string_word(info,1)
                if price is None: price=data_word(info,8)
            except Exception: pass
        return {'safety':{'state':safety_state,'verified':ver.get('verified'),'proxy':ver.get('proxy'),'suspicious':suspicious,'contract_name':ver.get('contract_name')},'supply':supply,'mint_price_wei':price,'name':snap_name,'ticker':snap_ticker,'is_hoodsea':is_hoodsea}

    def build_status(self,latest,from_block,to_block,started_at):
        now=int(time.time()); launches=self.db.launches_map(); rows=self.db.recent_collections(now-3600)
        candidates=[]
        for row in rows[:config.MAX_CANDIDATES]:
            addr=row['collection']; launch=launches.get(addr.lower())
            snap=self.contract_snapshot(addr)
            price_wei=snap['mint_price_wei']
            if launch and launch.get('mint_price_wei') is not None:
                try: price_wei=int(launch['mint_price_wei'])
                except Exception: pass
            price_eth=(price_wei/1e18) if price_wei is not None else None
            events=self.db.mint_window(addr,now-3600)
            metrics=compute_metrics(events,now)
            market=self.market.collection_market(addr)
            if snap.get('is_hoodsea') and market.get('state')!='LIVE':
                sales=self.db.market_window(addr,now-86400)
                if sales:
                    vol_eth=sum((int(x['price_wei'])/1e18) for x in sales if x.get('price_wei') not in (None,''))
                    market={'state':'LIVE','source':'HOODSEA_NFTSOLD_ONCHAIN','sales_24h':len(sales),'volume_24h':0,'volume_eth_24h':round(vol_eth,8),'floor_price':None,'reason':'ONCHAIN_SECONDARY_SALES_OBSERVED'}
                elif market.get('state') in ('UNAVAILABLE','NOT_YET_OPEN'):
                    market={'state':'EARLY_ONCHAIN_ONLY','reason':'VERIFIED_HOODSEA; NO_SECONDARY_SALE_OBSERVED_IN_LOCAL_24H_WINDOW','source':'HOODSEA_CONTRACT'}
            scored=score_candidate(price_eth,metrics,snap['supply'],snap['safety'],market)
            c={'collection':addr,'standard':row['standard'],'name':(launch or {}).get('name') or snap.get('name'),'ticker':(launch or {}).get('ticker') or snap.get('ticker'),'mint_price_eth':price_eth,'metrics':metrics,'supply':snap['supply'],'safety':snap['safety'],'market':market,'score':scored['score'],'score_parts':scored['parts'],'sell_through':scored['sell_through'],'hard_gates':scored['hard_gates'],'qualified':scored['qualified'],'action':scored['action'],'explorer_url':f'https://robinhoodchain.blockscout.com/address/{addr}','opensea_url':f'https://opensea.io/assets/robinhood/{addr}'}
            candidates.append(c); self.db.add_observation(addr,c); self.db.observe_shadow(c,now)
        candidates.sort(key=lambda x:(x['qualified'],x['score'],x['metrics']['velocity_1m']),reverse=True)
        qualified=sum(1 for c in candidates if c['qualified'])
        outcomes=self.db.outcome_stats(); shadow=self.db.shadow_stats()
        chain_fresh=True
        latest_time=self.block_time(latest) if latest else now
        age=max(0,now-latest_time)
        if age>120: chain_fresh=False; self._diag('LIVE_DOCTOR','CHAIN_DATA_STALE',f'{age}s')
        readiness='READY' if chain_fresh else 'NOT_READY'
        status={'schema_version':'1.0','generated_at':now,'mode':'READ_ONLY','wallet_execution':'MANUAL_ONLY','chain':{'name':'Robinhood Chain','chain_id':config.CHAIN_ID,'latest_block':latest,'latest_block_age_seconds':age,'rpc':config.DEFAULT_RPC_URL,'hoodsea_launchpad':config.HOODSEA_LAUNCHPAD},'status':f'SCANNING {from_block}-{to_block}','money_readiness':'QUALIFIED OPPORTUNITY AVAILABLE' if qualified else 'WAIT FOR QUALIFIED OPPORTUNITY','live_ready':readiness,'realized_net_usd':round(outcomes['realized_net_usd'],4),'capital_deployed_usd':round(outcomes['capital_deployed_usd'],4),'net_capital_day_pct':round(outcomes['net_capital_day_pct'],4),'win_rate_pct':round(outcomes['win_rate_pct'],2),'prediction_mae':None,'scan':{'from_block':from_block,'to_block':to_block,'blocks_processed':max(0,to_block-from_block+1),'total_mint_units_stored':self.db.total_mints(),'secondary_sales_stored':self.db.total_market_sales(),'hoodsea_launches_stored':self.db.total_launches(),'live_observations':len(candidates),'qualified_candidates':qualified,'duration_seconds':round(time.time()-started_at,3)},'best_live_observation':candidates[0] if candidates else None,'watchlist':candidates[:10],'manual_packages':[c for c in candidates if c['qualified']][:5],'learning':{'status':'PREDICTION_UNCERTIFIED' if outcomes['samples']<30 else 'OUTCOME_SAMPLE_AVAILABLE','qualified_samples':outcomes['samples'],'observed_win_rate_pct':round(outcomes['win_rate_pct'],2),'brier':None,'ece':None,'shadow':shadow},'diagnostics':self.diag[-10:],'limitations':['OpenSea stats require OPENSEA_API_KEY; verified free Hoodsea collections can instead use conservative EARLY_ONCHAIN_ONLY evidence, while other missing-market cases fail closed.','Recent mint concentration is a recent-flow proxy, not full current ownership concentration.','Public GitHub Pages snapshots are periodic; the local runner is the continuous scanner.']}
        return status

    def scan_once(self, public_lookback=None):
        started=time.time(); self.diag=[]
        chain=self.rpc.chain_id()
        if chain!=config.CHAIN_ID: raise RPCError(f'WRONG_CHAIN_ID:{chain}')
        latest=self.rpc.block_number()
        last=self.db.last_block()
        if public_lookback is not None:
            from_block=max(0,latest-public_lookback+1); to_block=latest
        elif last is None:
            from_block=max(0,latest-config.INITIAL_LOOKBACK_BLOCKS+1); to_block=latest
        else:
            from_block=last+1; to_block=min(latest,from_block+config.CHUNK_BLOCKS-1)
            if from_block>latest: from_block=to_block=latest
        self.scan_logs(from_block,to_block)
        self.db.set_meta('last_block',to_block)
        return self.build_status(latest,from_block,to_block,started)


def write_status(path,status):
    os.makedirs(os.path.dirname(path) or '.',exist_ok=True)
    tmp=path+'.tmp'
    with open(tmp,'w') as f: json.dump(status,f,indent=2,sort_keys=True)
    os.replace(tmp,path)
