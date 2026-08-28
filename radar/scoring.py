from collections import Counter


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def compute_metrics(events, now):
    def qty(seconds):
        return sum(int(e.get('quantity',1)) for e in events if now - int(e['block_time']) <= seconds)
    q1,q5,q15,q60 = qty(60),qty(300),qty(900),qty(3600)
    v1=q1/1.0
    v5=q5/5.0
    prev5=max(0, q15-q5)/10.0
    accel=((v5/prev5)-1.0) if prev5>0 else (1.0 if v5>0 else 0.0)
    recipients=[e.get('recipient') for e in events if e.get('recipient')]
    c=Counter(recipients)
    total=sum(c.values())
    top_share=(max(c.values())/total) if total else None
    return {
      'mints_1m':q1,'mints_5m':q5,'mints_15m':q15,'mints_60m':q60,
      'velocity_1m':round(v1,3),'velocity_5m':round(v5,3),
      'acceleration_5m':round(accel,3),'unique_recent_minters':len(c),
      'recent_mint_concentration':round(top_share,4) if top_share is not None else None,
    }


def score_candidate(mint_price_eth, metrics, supply, safety, market):
    parts={}
    if mint_price_eth is None:
        parts['price_asymmetry']=0
    elif mint_price_eth == 0:
        parts['price_asymmetry']=15
    elif mint_price_eth <= 0.00003:
        parts['price_asymmetry']=13
    elif mint_price_eth <= 0.0001:
        parts['price_asymmetry']=10
    else:
        parts['price_asymmetry']=3

    parts['mint_velocity']=int(_clamp(metrics.get('velocity_1m',0)*1.5,0,20))
    accel=metrics.get('acceleration_5m',0)
    parts['acceleration']=int(_clamp(max(0,accel)*7.5,0,15))

    total=supply.get('total_supply')
    maximum=supply.get('max_supply')
    sell=None
    if total is not None and maximum and maximum>0:
        sell=_clamp(total/maximum,0,1)
    parts['sell_through']=int(10*sell) if sell is not None else 0

    if market.get('state')=='LIVE':
        sales24=float(market.get('sales_24h') or 0)
        vol=float(market.get('volume_24h') or 0)
        parts['secondary_liquidity']=int(_clamp(sales24/3 + vol/250,0,15))
    else:
        parts['secondary_liquidity']=0

    parts['holder_growth']=int(_clamp(metrics.get('unique_recent_minters',0)/2,0,10))
    concentration=metrics.get('recent_mint_concentration')
    parts['distribution']=5 if concentration is not None and concentration<=0.08 else (3 if concentration is not None and concentration<=0.20 else 0)
    parts['safety']=10 if safety.get('state')=='PASS' else (4 if safety.get('state')=='REVIEW' else 0)
    total_score=sum(parts.values())

    hard=[]
    if safety.get('state')=='REJECT': hard.append('SAFETY_REJECT')
    if safety.get('verified') is False: hard.append('UNVERIFIED_CONTRACT')
    if market.get('state') not in ('LIVE','NOT_YET_OPEN'): hard.append('MARKET_EVIDENCE_UNAVAILABLE')
    if mint_price_eth is None: hard.append('MINT_PRICE_UNKNOWN')
    qualified=total_score>=85 and not hard
    action='MANUAL_MINT_CANDIDATE' if qualified else ('WATCH' if total_score>=60 else 'WAIT')
    return {'score':total_score,'parts':parts,'sell_through':sell,'hard_gates':hard,'qualified':qualified,'action':action}
