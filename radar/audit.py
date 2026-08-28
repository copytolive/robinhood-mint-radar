import json,os,platform,sys,time
from . import config
from .db import RadarDB
from .rpc import RPCClient
from .relevance import evaluate_relevance

def run(db_path=None,status_path=None):
    checks=[]
    def add(name,ok,detail=None,severity='BLOCKER'):checks.append({'name':name,'status':'PASS' if ok else ('WARN' if severity=='WARN' else 'FAIL'),'detail':detail})
    add('python_3_10_plus',sys.version_info>=(3,10),platform.python_version());add('wallet_manual_only',True,'no signing path')
    try:
        rpc=RPCClient(config.DEFAULT_RPC_URL);cid=rpc.chain_id();add('chain_id_4663',cid==4663,cid);tip=rpc.block_number();add('robinhood_rpc_live',tip>0,tip);add('seaport_1_6_deployed',rpc.code(config.SEAPORT_16) not in ('0x','0x0'),config.SEAPORT_16)
    except Exception as exc:add('robinhood_rpc_live',False,str(exc))
    add('position_manager_rejected',evaluate_relevance('ERC721','NonfungiblePositionManager','contract NonfungiblePositionManager{}')['state']=='REJECT')
    try:
        db=RadarDB(db_path or config.DEFAULT_DB);h=db.db_health();add('sqlite_integrity',h['integrity']=='ok',h);add('sqlite_wal',h['journal_mode'].lower()=='wal',h['journal_mode'],severity='WARN');db.close()
    except Exception as exc:add('sqlite_integrity',False,str(exc))
    sp=status_path or config.STATUS_PATH
    if os.path.exists(sp):
        try:
            s=json.load(open(sp));add('status_schema_1_3_plus',float(s.get('schema_version','0'))>=1.3,s.get('schema_version'));add('status_wallet_manual',s.get('wallet_execution')=='MANUAL_ONLY',s.get('wallet_execution'));age=int(time.time())-int(s.get('generated_at',0));add('status_fresh',age<180,f'age_seconds={age}',severity='WARN')
        except Exception as exc:add('status_parse',False,str(exc))
    else:add('status_exists',False,sp,severity='WARN')
    if platform.system()=='Darwin':
        for label in ('com.copytolive.robinhood-mint-radar','com.copytolive.robinhood-mint-radar-dashboard'):add(label+'_installed',os.path.exists(os.path.expanduser(f'~/Library/LaunchAgents/{label}.plist')),severity='WARN')
    return {'overall':'FAIL' if any(x['status']=='FAIL' for x in checks) else 'PASS','platform':platform.platform(),'checks':checks}
def main():
    out=run();print(json.dumps(out,indent=2));return 0 if out['overall']=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
