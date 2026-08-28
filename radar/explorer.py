import json
import urllib.parse
import urllib.request
from .safety import analyze_source

class BlockscoutClient:
    def __init__(self, base_api, timeout=12):
        self.base_api=base_api
        self.timeout=timeout

    def verification(self,address):
        url=self.base_api+'?'+urllib.parse.urlencode({'module':'contract','action':'getsourcecode','address':address})
        try:
            req=urllib.request.Request(url,headers={'accept':'application/json','user-agent':'copytolive-robinhood-mint-radar/1.2'})
            with urllib.request.urlopen(req,timeout=self.timeout) as r:
                data=json.loads(r.read().decode())
            result=data.get('result') or []
            if not result or not isinstance(result,list):
                return {'verified':None,'proxy':None,'source_available':False,'hard_risks':[],'review_risks':['VERIFICATION_RESPONSE_EMPTY'],'capabilities':[],'source_text':''}
            item=result[0] or {}
            source=item.get('SourceCode') or ''
            abi=item.get('ABI') or ''
            verified=bool(source and 'not verified' not in abi.lower())
            proxy=str(item.get('Proxy','0'))=='1'
            source_analysis=analyze_source(source,proxy=proxy)
            return {
              'verified':verified,
              'proxy':proxy,
              'source_available':bool(source),
              'hard_risks':source_analysis['hard_risks'],
              'review_risks':source_analysis['review_risks'],
              'capabilities':source_analysis['capabilities'],
              'contract_name':item.get('ContractName'),
              'source_text':source,
            }
        except Exception as exc:
            return {
              'verified':None,'proxy':None,'source_available':False,
              'hard_risks':[],'review_risks':['VERIFICATION_UNAVAILABLE'],
              'capabilities':[],'source_text':'',
              'reason':f'BLOCKSCOUT_ERROR:{type(exc).__name__}'
            }
