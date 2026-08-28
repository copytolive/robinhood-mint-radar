import argparse
import json
import sys
import time
from . import config
from .notify import notify_qualified
from .scanner import RadarScanner, write_status


def degraded_status(exc):
    now=int(time.time())
    return {'schema_version':'1.3','generated_at':now,'mode':'READ_ONLY','wallet_execution':'MANUAL_ONLY','status':'DEGRADED','money_readiness':'WAIT FOR QUALIFIED OPPORTUNITY','live_ready':'NOT_READY','scan':{'blocks_processed':0,'total_mint_units_stored':0,'hoodsea_launches_stored':0,'live_observations':0,'qualified_candidates':0},'best_live_observation':None,'watchlist':[],'manual_packages':[],'learning':{'status':'PREDICTION_UNCERTIFIED','qualified_samples':0},'diagnostics':[{'stage':'BOOTSTRAP','reason':'LIVE_SCAN_FAILED','error':f'{type(exc).__name__}: {exc}','ts':now}],'limitations':['No live opportunity may be approved while chain data is unavailable.']}


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
            status=scanner.scan_once(public_lookback=args.public_lookback)
            write_status(args.status,status)
            alert=notify_qualified(status,scanner.db)
            print(json.dumps({'live_ready':status['live_ready'],'latest_block':status.get('chain',{}).get('latest_block'),'qualified':status['scan']['qualified_candidates'],'alert':alert.get('state'),'status_path':args.status}))
        except Exception as exc:
            status=degraded_status(exc); write_status(args.status,status)
            print(json.dumps({'live_ready':'NOT_READY','error':str(exc),'status_path':args.status}),file=sys.stderr)
            if args.strict:return 2
        finally:
            if scanner:scanner.close()
        if args.once:return 0
        time.sleep(args.interval)

if __name__=='__main__':raise SystemExit(main())
