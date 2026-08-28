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
    return {'schema_version':'1.3','generated_at':now,'mode':'READ_ONLY','wallet_execution':'MANUAL_ONLY','status':'DEGRADED','money_readiness':'WAIT FOR QUALIFIED OPPORTUNITY','live_ready':'NOT_READY','scan':{'blocks_processed':0,'lag_blocks':None,'total_mint_units_stored':0,'hoodsea_launches_stored':0,'live_observations':0,'qualified_candidates':0},'best_live_observation':None,'watchlist':[],'manual_packages':[],'learning':{'status':'PREDICTION_UNCERTIFIED','qualified_samples':0},'diagnostics':[{'stage':'BOOTSTRAP','reason':'LIVE_SCAN_FAILED','error':f'{type(exc).__name__}: {exc}','ts':now}],'limitations':['No live opportunity may be approved while chain data is unavailable.']}


def _block_candidate_while_catching_up(candidate):
    if not candidate:
        return
    gates=candidate.setdefault('hard_gates',[])
    if 'SCANNER_NOT_CAUGHT_UP' not in gates:
        gates.append('SCANNER_NOT_CAUGHT_UP')
    candidate['qualified']=False
    candidate['qualification_path']=None
    candidate['action']='WAIT'


def finalize_status(status):
    """Fail closed on scanner backlog, then stamp completion time."""
    scan=status.setdefault('scan',{})
    chain=status.get('chain') or {}
    safe=chain.get('safe_block')
    scanned_to=scan.get('to_block')
    try:
        lag=max(0,int(safe)-int(scanned_to))
    except (TypeError,ValueError):
        lag=None
    scan['lag_blocks']=lag

    if lag is None or lag>config.MAX_READY_LAG_BLOCKS:
        status['live_ready']='NOT_READY'
        status['money_readiness']='CATCHING UP — WAIT FOR LIVE TIP'
        status['manual_packages']=[]
        scan['qualified_candidates']=0
        for candidate in status.get('watchlist') or []:
            _block_candidate_while_catching_up(candidate)
        _block_candidate_while_catching_up(status.get('best_live_observation'))
        diagnostics=status.setdefault('diagnostics',[])
        diagnostics.append({'stage':'LIVE_DOCTOR','reason':'SCANNER_BACKLOG','error':f'lag_blocks={lag}; ready_threshold={config.MAX_READY_LAG_BLOCKS}','ts':int(time.time())})
        status['diagnostics']=diagnostics[-10:]

    status['generated_at']=int(time.time())
    return status


def main(argv=None):
    p=argparse.ArgumentParser(description='Read-only Robinhood Chain NFT mint radar')
    p.add_argument('--db',default=config.DEFAULT_DB)
    p.add_argument('--status',default=config.STATUS_PATH)
    p.add_argument('--once',action='store_true')
    p.add_argument('--public-lookback',type=int,default=None)
    p.add_argument('--interval',type=float,default=config.SCAN_INTERVAL)
    p.add_argument('--strict',action='store_true',help='exit nonzero on live scan failure')
    args=p.parse_args(argv)
    while True:
        scanner=None
        try:
            scanner=RadarScanner(args.db)
            status=finalize_status(scanner.scan_once(public_lookback=args.public_lookback))
            write_status(args.status,status)
            alert=notify_qualified(status,scanner.db)
            print(json.dumps({'live_ready':status['live_ready'],'latest_block':status.get('chain',{}).get('latest_block'),'scanner_lag':status.get('scan',{}).get('lag_blocks'),'qualified':status['scan']['qualified_candidates'],'alert':alert.get('state'),'status_path':args.status}))
        except Exception as exc:
            status=degraded_status(exc); write_status(args.status,status)
            print(json.dumps({'live_ready':'NOT_READY','error':str(exc),'status_path':args.status}),file=sys.stderr)
            if args.strict:return 2
        finally:
            if scanner:scanner.close()
        if args.once:return 0
        time.sleep(args.interval)

if __name__=='__main__':raise SystemExit(main())
