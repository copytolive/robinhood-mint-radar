import json
import urllib.error
import urllib.parse
import urllib.request
from .tls import urlopen

class OpenSeaClient:
    def __init__(self, api_key='', chain='robinhood', timeout=12):
        self.api_key=api_key
        self.chain=chain
        self.timeout=timeout

    def _get(self, url):
        if not self.api_key:
            return None
        req=urllib.request.Request(url,headers={'x-api-key':self.api_key,'accept':'application/json','user-agent':'copytolive-robinhood-mint-radar/1.0'})
        with urlopen(req,timeout=self.timeout) as r:
            return json.loads(r.read().decode())

    def collection_market(self,address):
        if not self.api_key:
            return {'state':'UNAVAILABLE','reason':'OPENSEA_API_KEY_NOT_CONFIGURED'}
        try:
            nfts=self._get(f'https://api.opensea.io/api/v2/chain/{urllib.parse.quote(self.chain)}/contract/{address}/nfts?limit=1') or {}
            items=nfts.get('nfts') or []
            if not items:
                return {'state':'NOT_YET_OPEN','reason':'NO_OPENSEA_NFT_INDEXED'}
            token_id=str(items[0].get('identifier',''))
            col=self._get(f'https://api.opensea.io/api/v2/chain/{urllib.parse.quote(self.chain)}/contract/{address}/nfts/{urllib.parse.quote(token_id)}/collection') or {}
            slug=col.get('collection') or col.get('slug')
            if isinstance(slug,dict): slug=slug.get('slug')
            if not slug:
                return {'state':'NOT_YET_OPEN','reason':'COLLECTION_SLUG_NOT_INDEXED'}
            stats=self._get(f'https://api.opensea.io/api/v2/collections/{urllib.parse.quote(slug)}/stats') or {}
            total=stats.get('total') or {}
            intervals=stats.get('intervals') or []
            d1=next((x for x in intervals if x.get('interval') in ('one_day','1d','24h')), {})
            return {
              'state':'LIVE','slug':slug,
              'floor_price':total.get('floor_price'),
              'volume_total':total.get('volume'),
              'sales_total':total.get('sales'),
              'owners':total.get('num_owners'),
              'volume_24h':d1.get('volume',0),
              'sales_24h':d1.get('sales',0),
            }
        except urllib.error.HTTPError as exc:
            return {'state':'UNAVAILABLE','reason':f'OPENSEA_HTTP_{exc.code}'}
        except Exception as exc:
            return {'state':'UNAVAILABLE','reason':f'OPENSEA_ERROR:{type(exc).__name__}'}
