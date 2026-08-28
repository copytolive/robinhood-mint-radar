import json
import urllib.parse
import urllib.request
from .safety import analyze_source
from .tls import urlopen

class BlockscoutClient:
    def __init__(self,base_api,timeout=12,v2_base=None):
        self.base_api=base_api; self.timeout=timeout
        self.v2_base=v2_base or base_api.rsplit('/api',1)[0]+'/api/v2'

    def _get_json(self,url):
        req=urllib.request.Request(url,headers={'accept':'application/json','user-agent':'copytolive-robinhood-mint-radar/1.3'})
        with urlopen(req,timeout=self.timeout) as r:return json.loads(r.read().decode())

    def verification(self,address):
        url=self.base_api+'?'+urllib.parse.urlencode({'module':'contract','action':'getsourcecode','address':address})
        try:
            data=self._get_json(url); result=data.get('result') or []
            if not result or not isinstance(result,list): return {'verified':None,'proxy':None,'source_available':False,'hard_risks':[],'review_risks':['VERIFICATION_RESPONSE_EMPTY'],'capabilities':[],'source_text':''}
            item=result[0] or {}; source=item.get('SourceCode') or ''; abi=item.get('ABI') or ''
            verified=bool(source and 'not verified' not in abi.lower()); proxy=str(item.get('Proxy','0'))=='1'
            a=analyze_source(source,proxy=proxy)
            return {'verified':verified,'proxy':proxy,'source_available':bool(source),'hard_risks':a['hard_risks'],'review_risks':a['review_risks'],'capabilities':a['capabilities'],'contract_name':item.get('ContractName'),'source_text':source}
        except Exception as exc:
            return {'verified':None,'proxy':None,'source_available':False,'hard_risks':[],'review_risks':['VERIFICATION_UNAVAILABLE'],'capabilities':[],'source_text':'','reason':f'BLOCKSCOUT_ERROR:{type(exc).__name__}'}

    def ownership(self,address,total_supply=None):
        try:
            holders=self._get_json(f'{self.v2_base}/tokens/{address}/holders')
            counters=self._get_json(f'{self.v2_base}/tokens/{address}/counters')
            items=holders.get('items') or []
            vals=[]
            for item in items:
                try: vals.append(int(item.get('value') or 0))
                except Exception: pass
            raw_count=counters.get('token_holders_count')
            try:counter_count=int(raw_count) if raw_count not in (None,'') else None
            except Exception:counter_count=None
            sampled=len(items); complete=not bool(holders.get('next_page_params'))
            counter_consistent=counter_count is None or counter_count>=sampled
            holder_count=counter_count if counter_consistent else None
            denom=int(total_supply or 0)
            if denom<=0 and complete: denom=sum(vals)
            top=(max(vals)/denom) if vals and denom>0 else None
            out={'state':'LIVE','holders_count':holder_count,'sampled_holders':sampled,'top_holder_share':round(top,6) if top is not None else None,'complete_page':complete,'source':'BLOCKSCOUT_V2'}
            if not counter_consistent:
                out['holders_count_state']='INCONSISTENT'
                out['holders_count_lower_bound']=sampled
                out['reason']='BLOCKSCOUT_HOLDER_COUNTER_LT_SAMPLE'
            else:
                out['holders_count_state']='LIVE'
            return out
        except Exception as exc:
            return {'state':'UNAVAILABLE','reason':f'BLOCKSCOUT_HOLDERS_ERROR:{type(exc).__name__}','source':'BLOCKSCOUT_V2'}
