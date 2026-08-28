import argparse,json
from . import config
from .db import RadarDB

def main(argv=None):
    p=argparse.ArgumentParser(description='Record a manual realized outcome; no wallet actions are performed.')
    p.add_argument('--db',default=config.DEFAULT_DB)
    p.add_argument('--collection',required=True)
    p.add_argument('--decision',default='MINT')
    p.add_argument('--entry-cost-usd',required=True,type=float)
    p.add_argument('--exit-value-usd',required=True,type=float)
    p.add_argument('--gas-usd',default=0.0,type=float)
    p.add_argument('--package-id',default=None)
    a=p.parse_args(argv)
    db=RadarDB(a.db)
    try:
        net=db.record_outcome(a.collection,a.decision,a.entry_cost_usd,a.exit_value_usd,a.gas_usd,a.package_id)
        print(json.dumps({'recorded':True,'collection':a.collection,'realized_net_usd':net}))
    finally: db.close()
    return 0

if __name__=='__main__': raise SystemExit(main())
