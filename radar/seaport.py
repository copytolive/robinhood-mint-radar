NFT_TYPES={2,3,4,5}
PAYMENT_TYPES={0,1}
ZERO='0x'+'0'*40

def _raw(data_hex):
    return bytes.fromhex(data_hex[2:] if (data_hex or '').startswith('0x') else (data_hex or ''))

def _word(raw, offset):
    chunk=raw[offset:offset+32]
    if len(chunk)!=32: raise ValueError('short ABI word')
    return int.from_bytes(chunk,'big')

def _address(raw, offset):
    chunk=raw[offset:offset+32]
    if len(chunk)!=32: raise ValueError('short ABI address')
    return '0x'+chunk[-20:].hex()

def _topic_address(topic):
    return '0x'+topic[-40:] if topic and len(topic)>=42 else None

def _parse_static_array(raw, offset, width):
    n=_word(raw,offset)
    out=[]
    p=offset+32
    for _ in range(n):
        vals=[_word(raw,p+32*i) for i in range(width)]
        token='0x'+raw[p+32+12:p+64].hex()
        if width==4:
            out.append({'item_type':vals[0],'token':token,'identifier':vals[2],'amount':vals[3]})
        else:
            recipient='0x'+raw[p+32*4+12:p+32*5].hex()
            out.append({'item_type':vals[0],'token':token,'identifier':vals[2],'amount':vals[3],'recipient':recipient})
        p += 32*width
    return out

def decode_order_fulfilled(data_hex, topics):
    raw=_raw(data_hex)
    if len(raw)<128: raise ValueError('short OrderFulfilled data')
    order_hash='0x'+raw[0:32].hex()
    recipient=_address(raw,32)
    offer_off=_word(raw,64)
    cons_off=_word(raw,96)
    offer=_parse_static_array(raw,offer_off,4)
    consideration=_parse_static_array(raw,cons_off,5)
    return {
      'order_hash':order_hash,
      'offerer':_topic_address(topics[1]) if len(topics)>1 else None,
      'zone':_topic_address(topics[2]) if len(topics)>2 else None,
      'recipient':recipient,
      'offer':offer,
      'consideration':consideration,
    }

def sale_records(event):
    offer_nft=[x for x in event['offer'] if x['item_type'] in NFT_TYPES]
    cons_nft=[x for x in event['consideration'] if x['item_type'] in NFT_TYPES]
    offer_pay=[x for x in event['offer'] if x['item_type'] in PAYMENT_TYPES]
    cons_pay=[x for x in event['consideration'] if x['item_type'] in PAYMENT_TYPES]
    if offer_nft and cons_pay:
        nfts=offer_nft; pays=cons_pay; seller=event.get('offerer'); buyer=event.get('recipient')
    elif cons_nft and offer_pay:
        nfts=cons_nft; pays=offer_pay; buyer=event.get('offerer'); seller=None
    else:
        return []
    native=sum(int(x['amount']) for x in pays if x['item_type']==0)
    erc20=[x for x in pays if x['item_type']==1]
    payment_token=erc20[0]['token'] if erc20 and all(x['token'].lower()==erc20[0]['token'].lower() for x in erc20) else None
    payment_amount=sum(int(x['amount']) for x in erc20) if payment_token else None
    bundle=len(nfts)
    out=[]
    for x in nfts:
        out.append({
          'collection':x['token'],
          'token_id':str(x['identifier']),
          'quantity':int(x['amount']),
          'price_wei':native if native and bundle==1 else None,
          'payment_token':payment_token,
          'payment_amount':payment_amount if bundle==1 else None,
          'seller':seller,'buyer':buyer,
          'order_hash':event.get('order_hash'),
          'bundle_size':bundle,
          'source':'SEAPORT_1_6',
        })
    return out
