from collections import Counter

def _clamp(v,lo,hi):return max(lo,min(hi,v))
def compute_metrics(events,now):
    def event_count(seconds):return sum(1 for e in events if now-int(e['block_time'])<=seconds)
    def raw_units(seconds):return sum(int(e.get('quantity',1)) for e in events if now-int(e['block_time'])<=seconds)
    q1,q5,q15,q60=event_count(60),event_count(300),event_count(900),event_count(3600);v1=q1/1.0;v5=q5/5.0;prev5=max(0,q15-q5)/10.0;accel=(v5/prev5-1.0) if prev5>0 else (1.0 if v5>0 else 0.0);recipients=[e.get('recipient') for e in events if e.get('recipient')];c=Counter(recipients);total=sum(c.values());top=max(c.values())/total if total else None
    return {'mints_1m':q1,'mints_5m':q5,'mints_15m':q15,'mints_60m':q60,'raw_units_1m':raw_units(60),'raw_units_5m':raw_units(300),'velocity_1m':round(v1,3),'velocity_5m':round(v5,3),'acceleration_5m':round(accel,3),'unique_recent_minters':len(c),'recent_mint_concentration':round(top,4) if top is not None else None}
def score_candidate(mint_price_eth,metrics,supply,safety,market,relevance=None,is_hoodsea=False,launch=False,ownership=None,execution=None):
    relevance=relevance or {'state':'PASS'};ownership=ownership or {'state':'UNAVAILABLE'};execution=execution or {'state':'TRUSTED'};parts={}
    parts['price_asymmetry']=0 if mint_price_eth is None else (15 if mint_price_eth==0 else (13 if mint_price_eth<=0.00003 else (10 if mint_price_eth<=0.0001 else 3)))
    parts['mint_velocity']=int(_clamp(metrics.get('velocity_1m',0)*1.5,0,20));parts['acceleration']=int(_clamp(max(0,metrics.get('acceleration_5m',0))*7.5,0,15));total=supply.get('total_supply');maximum=supply.get('max_supply');sell=_clamp(total/maximum,0,1) if total is not None and maximum and maximum>0 else None;parts['sell_through']=int(10*sell) if sell is not None else 0
    if market.get('state')=='LIVE':parts['secondary_liquidity']=int(_clamp(float(market.get('sales_24h') or 0)*1.5+float(market.get('volume_eth_24h') or 0)*40+float(market.get('volume_24h') or 0)/250,0,15))
    else:parts['secondary_liquidity']=0
    parts['holder_growth']=int(_clamp(metrics.get('unique_recent_minters',0)/2,0,10));current=ownership.get('top_holder_share') if ownership.get('state')=='LIVE' else None;recent=metrics.get('recent_mint_concentration');conc=current if current is not None else recent;parts['distribution']=5 if conc is not None and conc<=0.08 else (3 if conc is not None and conc<=0.20 else 0);parts['safety']=10 if safety.get('state')=='PASS' else (4 if safety.get('state')=='REVIEW' else 0);score=sum(parts.values());hard=[]
    if relevance.get('state')=='REJECT':hard.append('NFT_RELEVANCE_REJECT')
    elif relevance.get('state')!='PASS':hard.append('NFT_RELEVANCE_NOT_PASS')
    if safety.get('state')=='REJECT':hard.append('SAFETY_REJECT')
    elif safety.get('state')!='PASS':hard.append('SAFETY_REVIEW_REQUIRED')
    if safety.get('verified') is False:hard.append('UNVERIFIED_CONTRACT')
    if mint_price_eth is None:hard.append('MINT_PRICE_UNKNOWN')
    if current is not None and current>0.25:hard.append('OWNERSHIP_CONCENTRATION_HIGH')
    if execution.get('state')!='TRUSTED':hard.append('TRUSTED_EXECUTION_SURFACE_UNAVAILABLE')
    ms=market.get('state');regular=ms=='LIVE';early=False
    if ms=='EARLY_ONCHAIN_ONLY':
        early=bool(is_hoodsea and launch and mint_price_eth==0 and relevance.get('state')=='PASS' and safety.get('state')=='PASS' and metrics.get('unique_recent_minters',0)>=20 and metrics.get('velocity_5m',0)>=2 and sell is not None and sell>=0.10)
        if not early:hard.append('EARLY_ONCHAIN_REQUIREMENTS_NOT_MET')
    elif not regular:hard.append('MARKET_EVIDENCE_UNAVAILABLE')
    rq=regular and score>=85 and not hard;eq=early and score>=80 and not hard;qualified=rq or eq;return {'score':score,'parts':parts,'sell_through':sell,'hard_gates':hard,'qualified':qualified,'action':'MANUAL_MINT_CANDIDATE' if qualified else ('WATCH' if score>=60 and relevance.get('state')!='REJECT' else 'WAIT'),'qualification_path':'EARLY_ONCHAIN_ONLY' if eq else ('MARKET_CONFIRMED' if rq else None)}
