def probability_from_score(score):
    s=max(0.0,min(100.0,float(score or 0)))
    return round(max(0.02,min(0.95,0.02 + 0.93*(s/100.0)**2)),4)

def calibration_metrics(samples, min_certified=100):
    rows=[]
    for x in samples:
        try:
            p=float(x['predicted_probability'])
            y=1.0 if float(x['outcome'])>0 else 0.0
        except Exception:
            continue
        if 0<=p<=1: rows.append((p,y))
    n=len(rows)
    if not n:
        return {'status':'PREDICTION_UNCERTIFIED','samples':0,'brier':None,'ece':None,'mae':None,'buckets':[]}
    brier=sum((p-y)**2 for p,y in rows)/n
    mae=sum(abs(p-y) for p,y in rows)/n
    buckets=[]
    ece=0.0
    for lo in [i/10 for i in range(10)]:
        hi=lo+0.1
        vals=[(p,y) for p,y in rows if (lo<=p<hi) or (hi>=1 and p==1)]
        if not vals:
            buckets.append({'range':f'{int(lo*100)}-{int(hi*100)}','samples':0,'mean_predicted':None,'observed_rate':None})
            continue
        mp=sum(p for p,_ in vals)/len(vals); oy=sum(y for _,y in vals)/len(vals)
        ece += len(vals)/n*abs(mp-oy)
        buckets.append({'range':f'{int(lo*100)}-{int(hi*100)}','samples':len(vals),'mean_predicted':round(mp,4),'observed_rate':round(oy,4)})
    if n < 30:
        status='PREDICTION_UNCERTIFIED'
    elif n < min_certified:
        status='CALIBRATION_WARMUP'
    elif ece<=0.10 and brier<=0.25:
        status='CALIBRATED'
    else:
        status='NEEDS_RECALIBRATION'
    return {'status':status,'samples':n,'brier':round(brier,4),'ece':round(ece,4),'mae':round(mae,4),'buckets':buckets}
