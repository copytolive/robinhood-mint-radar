import json
import threading
import time
import urllib.error
import urllib.request
from .tls import urlopen

class RPCError(RuntimeError): pass

class RPCClient:
    def __init__(self,url,timeout=15,retries=4):
        self.url=url; self.timeout=timeout; self.retries=retries; self._id=0; self._id_lock=threading.Lock()

    def _next_id(self):
        with self._id_lock:
            self._id+=1
            return self._id

    def call(self,method,params=None):
        params=params or []; last=None
        for attempt in range(self.retries+1):
            request_id=self._next_id()
            payload=json.dumps({'jsonrpc':'2.0','id':request_id,'method':method,'params':params}).encode()
            req=urllib.request.Request(self.url,data=payload,headers={'content-type':'application/json','user-agent':'copytolive-robinhood-mint-radar/1.4'})
            try:
                with urlopen(req,timeout=self.timeout) as resp: body=json.loads(resp.read().decode())
                if 'error' in body: raise RPCError(f"{method}: {body['error']}")
                return body.get('result')
            except (urllib.error.URLError,TimeoutError,OSError,json.JSONDecodeError,RPCError) as exc:
                last=exc
                if attempt<self.retries: time.sleep(min(2.0,0.5*(attempt+1)))
        raise RPCError(f'{method} failed after retries: {last}')

    def chain_id(self): return int(self.call('eth_chainId'),16)
    def block_number(self): return int(self.call('eth_blockNumber'),16)
    def block(self,number): return self.call('eth_getBlockByNumber',[hex(number),False])
    def transaction(self,tx_hash): return self.call('eth_getTransactionByHash',[tx_hash])
    def _logs_once(self,from_block,to_block,topics,address=None):
        q={'fromBlock':hex(from_block),'toBlock':hex(to_block),'topics':topics}
        if address:q['address']=address
        return self.call('eth_getLogs',[q]) or []
    def logs(self,from_block,to_block,topics,address=None):
        """Read logs without silently skipping a provider-limited range."""
        try:
            return self._logs_once(from_block,to_block,topics,address)
        except RPCError:
            if int(to_block)<=int(from_block):
                raise
            mid=(int(from_block)+int(to_block))//2
            left=self.logs(int(from_block),mid,topics,address)
            right=self.logs(mid+1,int(to_block),topics,address)
            return left+right
    def code(self,address,block='latest'): return self.call('eth_getCode',[address,block]) or '0x'
    def eth_call(self,address,data,block='latest'): return self.call('eth_call',[{'to':address,'data':data},block]) or '0x'
    def sha3_text(self,text): return self.call('web3_sha3',['0x'+text.encode().hex()])
    def selector(self,signature): return self.sha3_text(signature)[:10]
