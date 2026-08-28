import json
import urllib.parse
import urllib.request

class BlockscoutClient:
    def __init__(self, base_api, timeout=12):
        self.base_api=base_api
        self.timeout=timeout

    def verification(self,address):
        url=self.base_api+'?'+urllib.parse.urlencode({'module':'contract','action':'getsourcecode','address':address})
        try:
            req=urllib.request.Request(url,headers={'accept':'application/json','user-agent':'copytolive-robinhood-mint-radar/1.0'})
            with urllib.request.urlopen(req,timeout=self.timeout) as r:
                data=json.loads(r.read().decode())
            result=data.get('result') or []
            if not result or not isinstance(result,list):
                return {'verified':None,'proxy':None,'source_available':False}
            item=result[0] or {}
            source=item.get('SourceCode') or ''
            abi=item.get('ABI') or ''
            verified=bool(source and 'not verified' not in abi.lower())
            low=source.lower()
            suspicious=[]
            for needle,label in [('selfdestruct','SELFDESTRUCT_SOURCE'),('delegatecall','DELEGATECALL_SOURCE'),('setmaxsupply','MUTABLE_MAX_SUPPLY'),('setmintprice','MUTABLE_MINT_PRICE')]:
                if needle in low: suspicious.append(label)
            proxy=str(item.get('Proxy','0'))=='1'
            if proxy: suspicious.append('PROXY_CONTRACT')
            return {'verified':verified,'proxy':proxy,'source_available':bool(source),'suspicious':suspicious,'contract_name':item.get('ContractName')}
        except Exception as exc:
            return {'verified':None,'proxy':None,'source_available':False,'reason':f'BLOCKSCOUT_ERROR:{type(exc).__name__}'}
