import argparse
import json
import sys
import time
from . import config
from .notify import notify_qualified
from .live_scanner import LiveRadarScanner as RadarScanner
from .scanner import write_status


def degraded_status(exc):
    now=int(time.time())
    return {'schema_version':'1.3','generated_at':now,'mode':'READ_ONLY','wallet_execution':'MANUAL_ONLY','status':'DEGRADED','money_readiness':'WAIT FOR QUALIFIED OPPORTUNITY','live_ready':'NOT_READY','scan':{'blocks_processed':0,'lag_blocks':None,'lag_seconds':None,'analysis_age_seconds':None,'total_mint_units_stored':0,'hoodsea_launches_stored':0,'live_observations':0,'qualified_candidates':0},'best_live_observation':None,'watchlist':[],'manual_packages':[],'learning':{'status':'PREDICTION_UNCERTIFIED','qualified_samples':0},'diagnostics':[{'stage':'BOOTSTRAP','reason':'LIVE_SCAN_FAILED','error':f'{type(exc).__name__}: {exc}','ts':now}],'limitations':['No live opportunity may be approved while chain data is unavailable.']}


def _block_candidate(candidate,gate):
    if not candidate:
        return
    gates=candidate.setdefault('hard_gates',[])
    if gate not in gates:
        gates.append(gate)
    candidate['qualified']=False
    candidate['qualification_path']=None
    candidate['action']='WAIT'


def finalize_status(status):
    """Fail closed on stale ingest or stale candidate analysis, then timestamp."""
    scan=status.setdefault('scan',{})
    chain=status.get('chain') or {}
    safe=chain.get('safe_block')
    scanned_to=scan.get('to_block')
    try:
        lag_blocks=max(0,int(safe)-int(scanned_to))
    except (TypeError,ValueError):
        lag_blocks=None
    scan['lag_blocks']=lag_blocks

    lag_seconds=scan.get('lag_seconds')
    try:
        lag_seconds=None if lag_seconds is None else max(0,int(lag_seconds))
    except (TypeError,ValueError):
        lag_seconds=None
    scan['lag_seconds']=lag_seconds

    analysis_age=scan.get('analysis_age_seconds')
    try:
        analysis_age=None if analysis_age is None else max(0,float(analysis_age))
    except (TypeError,ValueError):
        analysis_age=None
    scan['analysis_age_seconds']=analysis_age

    # LiveScanner performs a tail-ingest after candidate enrichment. Keep the
    # headline range aligned with that durable cursor instead of the earlier
    # pre-enrichment range returned by BaseRadarScanner.build_status().
    scanned_from=scan.get('from_block')
    if scanned_from is not None and scanned_to is not None:
        status['status']=f'SCANNING {scanned_from}-{scanned_to}'

    block_stale=lag_blocks is None or lag_blocks>config.MAX_READY_LAG_BLOCKS
    time_stale=lag_seconds is not None and lag_seconds>config.MAX_READY_LAG_SECONDS
    analysis_stale=analysis_age is not None and analysis_age>config.MAX_READY_LAG_SECONDS

    if block_stale or time_stale or analysis_stale:
        status['live_ready']='NOT_READY'
        status['money_readiness']='CATCHING UP — WAIT FOR LIVE TIP' if (block_stale or time_stale) else 'ANALYSIS REFRESHING — WAIT'
        status['manual_packages']=[]
        scan['qualified_candidates']=0
        gate='SCANNER_NOT_CAUGHT_UP' if (block_stale or time_stale) else 'ANALYSIS_TOO_OLD'
        for candidate in status.get('watchlist') or []:
            _block_candidate(candidate,gate)
        _block_candidate(status.get('best_live_observation'),gate)
        diagnostics=status.setdefault('diagnostics',[])
        if block_stale or time_stale:
            diagnostics.append({'stage':'LIVE_DOCTOR','reason':'SCANNER_BACKLOG','error':f'lag_blocks={lag_blocks}/{config.MAX_READY_LAG_BLOCKS}; lag_seconds={lag_seconds}/{config.MAX_READY_LAG_SECONDS}','ts':int(time.time())})
        if analysis_stale:
            diagnostics.append({'stage':'LIVE_DOCTOR','reason':'ANALYSIS_STALE','error':f'analysis_age_seconds={analysis_age}/{config.MAX_READY_LAG_SECONDS}','ts':int(time.time())})
        status['diagnostics']=diagnostics[-10:]

    status['generated_at']=int(time.time())
    return status


def _strict_retryable(args,status=None):
    """Strict one-shot probes may retry transient/stale observations, never approve them."""
    return bool(args.strict and args.once and (status is None or status.get('live_ready')!='READY'))


def main(argv=None):
    p=argparse.ArgumentParser(description='Read-only Robinhood Chain NFT mint radar')
    p.add_argument('--db',default=config.DEFAULT_DB)
    p.add_argument('--status',default=config.STATUS_PATH)
    p.add_argument('--once',action='store_true')
    p.add_argument('--public-lookback',type=int,default=None)
    p.add_argument('--interval',type=float,default=config.SCAN_INTERVAL)
    p.add_argument('--strict',action='store_true',help='require a READY live scan; transient one-shot probes retry before failing')
    args=p.parse_args(argv)

    scanner=None
    strict_attempt=0
    strict_max_attempts=3 if args.strict and args.once else 1
    try:
        while True:
            strict_attempt+=1
            try:
                if scanner is None:
                    scanner=RadarScanner(args.db)
                status=finalize_status(scanner.scan_once(public_lookback=args.public_lookback))
                write_status(args.status,status)
                alert=notify_qualified(status,scanner.db)
                print(json.dumps({'live_ready':status['live_ready'],'latest_block':status.get('chain',{}).get('latest_block'),'scanner_lag_blocks':status.get('scan',{}).get('lag_blocks'),'scanner_lag_seconds':status.get('scan',{}).get('lag_seconds'),'analysis_age_seconds':status.get('scan',{}).get('analysis_age_seconds'),'qualified':status['scan']['qualified_candidates'],'alert':alert.get('state'),'status_path':args.status}))

                if _strict_retryable(args,status):
                    if strict_attempt<strict_max_attempts:
                        print(f'[RETRY] strict live probe {strict_attempt}/{strict_max_attempts} was NOT_READY; retrying with warm caches/checkpoint...',file=sys.stderr)
                        time.sleep(min(2.0,float(strict_attempt)))
                        continue
                    return 2
            except Exception as exc:
                status=degraded_status(exc);write_status(args.status,status)
                print(json.dumps({'live_ready':'NOT_READY','error':str(exc),'status_path':args.status}),file=sys.stderr)
                if scanner is not None:
                    scanner.close();scanner=None
                if _strict_retryable(args):
                    if strict_attempt<strict_max_attempts:
                        print(f'[RETRY] strict live probe {strict_attempt}/{strict_max_attempts} failed transiently; retrying...',file=sys.stderr)
                        time.sleep(min(2.0,float(strict_attempt)))
                        continue
                    return 2
                if args.strict:
                    return 2
            if args.once:
                return 0
            strict_attempt=0
            time.sleep(args.interval)
    finally:
        if scanner is not None:
            scanner.close()

if __name__=='__main__':raise SystemExit(main())
