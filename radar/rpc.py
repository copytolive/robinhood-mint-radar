import json
import time
import urllib.error
import urllib.request

class RPCError(RuntimeError):
    pass

class RPCClient:
    def __init__(self, url, timeout=15, retries=2):
        self.url = url
        self.timeout = timeout
        self.retries = retries
        self._id = 0

    def call(self, method, params=None):
        params = params or []
        last = None
        for attempt in range(self.retries + 1):
            self._id += 1
            payload = json.dumps({'jsonrpc':'2.0','id':self._id,'method':method,'params':params}).encode()
            req = urllib.request.Request(self.url, data=payload, headers={'content-type':'application/json','user-agent':'copytolive-robinhood-mint-radar/1.0'})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read().decode())
                if 'error' in body:
                    raise RPCError(f"{method}: {body['error']}")
                return body.get('result')
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RPCError) as exc:
                last = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
        raise RPCError(f'{method} failed after retries: {last}')

    def chain_id(self):
        return int(self.call('eth_chainId'), 16)

    def block_number(self):
        return int(self.call('eth_blockNumber'), 16)

    def block(self, number):
        return self.call('eth_getBlockByNumber', [hex(number), False])

    def logs(self, from_block, to_block, topics, address=None):
        q = {'fromBlock':hex(from_block),'toBlock':hex(to_block),'topics':topics}
        if address:
            q['address'] = address
        return self.call('eth_getLogs', [q]) or []

    def code(self, address, block='latest'):
        return self.call('eth_getCode', [address, block]) or '0x'

    def eth_call(self, address, data, block='latest'):
        return self.call('eth_call', [{'to':address,'data':data}, block]) or '0x'

    def sha3_text(self, text):
        raw = '0x' + text.encode().hex()
        return self.call('web3_sha3', [raw])

    def selector(self, signature):
        return self.sha3_text(signature)[:10]
