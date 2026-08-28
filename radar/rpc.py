import json
import os
import threading
import time
import urllib.error
import urllib.request
from .tls import urlopen

class RPCError(RuntimeError): pass

_OFFICIAL_MAINNET='https://rpc.mainnet.chain.robinhood.com'
_DEFAULT_PUBLIC_FALLBACKS=(
    'https://rpc.nodeflare.app/robinhood/public',
    'https://robinhood-mainnet-rpc.blockreq.com/v1/rpc/public',
)

class RPCClient:
    def __init__(self,url,timeout=15,retries=4,fallback_urls=None,expected_chain_id=None):
        primary=(url or '').strip().rstrip('/')
        if fallback_urls is None and primary==_OFFICIAL_MAINNET:
            raw=os.getenv('RH_RPC_FALLBACK_URLS')
            fallback_urls=([x.strip() for x in raw.split(',') if x.strip()] if raw is not None else list(_DEFAULT_PUBLIC_FALLBACKS))
            if expected_chain_id is None:expected_chain_id=4663
        urls=[url]+list(fallback_urls or [])
        self.urls=[]
        for item in urls:
            item=(item or '').strip()
            if item and item not in self.urls:self.urls.append(item)
        if not self.urls:raise ValueError('at least one RPC URL is required')
        self.url=self.urls[0]
        self.timeout=timeout;self.retries=retries;self.expected_chain_id=expected_chain_id
        self._id=0;self._id_lock=threading.Lock();self._state_lock=threading.Lock()
        self._active_idx=0;self._validated={};self.failovers=0

    def _next_id(self):
        with self._id_lock:
            self._id+=1
            return self._id

    def _request(self,url,method,params):
        request_id=self._next_id()
        payload=json.dumps({'jsonrpc':'2.0','id':request_id,'method':method,'params':params}).encode()
        req=urllib.request.Request(url,data=payload,headers={'content-type':'application/json','user-agent':'copytolive-robinhood-mint-radar/1.5'})
        with urlopen(req,timeout=self.timeout) as resp:body=json.loads(resp.read().decode())
        if 'error' in body:raise RPCError(f"{method}: {body['error']}")
        return body.get('result')

    def _verify_chain(self,url):
        if self.expected_chain_id is None:return
        if self._validated.get(url):return
        result=self._request(url,'eth_chainId',[])
        try:chain=int(result,16)
        except Exception as exc:raise RPCError(f'INVALID_CHAIN_ID:{url}:{result}') from exc
        if chain!=int(self.expected_chain_id):raise RPCError(f'WRONG_CHAIN_ID:{url}:{chain}')
        with self._state_lock:self._validated[url]=True

    def _mark_success(self,idx,url):
        with self._state_lock:
            if idx!=self._active_idx:self.failovers+=1
            self._active_idx=idx;self.url=url

    def call(self,method,params=None):
        params=params or [];errors=[]
        with self._state_lock:start=self._active_idx
        for offset in range(len(self.urls)):
            idx=(start+offset)%len(self.urls);url=self.urls[idx];last=None
            try:
                if method!='eth_chainId':self._verify_chain(url)
                for attempt in range(self.retries+1):
                    try:
                        result=self._request(url,method,params)
                        if method=='eth_chainId' and self.expected_chain_id is not None:
                            chain=int(result,16)
                            if chain!=int(self.expected_chain_id):raise RPCError(f'WRONG_CHAIN_ID:{url}:{chain}')
                            with self._state_lock:self._validated[url]=True
                        self._mark_success(idx,url)
                        return result
                    except (urllib.error.URLError,TimeoutError,OSError,json.JSONDecodeError,RPCError) as exc:
                        last=exc
                        if attempt<self.retries:time.sleep(min(1.0,0.25*(attempt+1)))
                raise RPCError(str(last))
            except (urllib.error.URLError,TimeoutError,OSError,json.JSONDecodeError,RPCError,ValueError) as exc:
                errors.append(f'{url}: {type(exc).__name__}: {exc}')
                continue
        raise RPCError(f"{method} failed on all RPC endpoints: {' | '.join(errors)}")

    def chain_id(self):return int(self.call('eth_chainId'),16)
    def block_number(self):return int(self.call('eth_blockNumber'),16)
    def block(self,number):return self.call('eth_getBlockByNumber',[hex(number),False])
    def transaction(self,tx_hash):return self.call('eth_getTransactionByHash',[tx_hash])
    def _logs_once(self,from_block,to_block,topics,address=None):
        q={'fromBlock':hex(from_block),'toBlock':hex(to_block),'topics':topics}
        if address:q['address']=address
        return self.call('eth_getLogs',[q]) or []
    def logs(self,from_block,to_block,topics,address=None):
        """Read logs without silently skipping a provider-limited range."""
        try:return self._logs_once(from_block,to_block,topics,address)
        except RPCError:
            if int(to_block)<=int(from_block):raise
            mid=(int(from_block)+int(to_block))//2
            left=self.logs(int(from_block),mid,topics,address)
            right=self.logs(mid+1,int(to_block),topics,address)
            return left+right
    def code(self,address,block='latest'):return self.call('eth_getCode',[address,block]) or '0x'
    def eth_call(self,address,data,block='latest'):return self.call('eth_call',[{'to':address,'data':data},block]) or '0x'
    def sha3_text(self,text):return self.call('web3_sha3',['0x'+text.encode().hex()])
    def selector(self,signature):return self.sha3_text(signature)[:10]
