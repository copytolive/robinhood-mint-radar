import argparse
import json
import os
import signal
import subprocess
import sys
import time

from .cli import degraded_status
from .scanner import write_status


_STOP=False
_CHILD=None


def _handle_signal(signum, frame):
    global _STOP, _CHILD
    _STOP=True
    if _CHILD is not None and _CHILD.poll() is None:
        try:_CHILD.terminate()
        except Exception:pass


def run_cycle(db,status,timeout_seconds):
    """Run exactly one radar cycle in an isolated subprocess with a hard deadline."""
    global _CHILD
    cmd=[sys.executable,'-m','radar','--once','--db',db,'--status',status]
    started=time.time()
    _CHILD=subprocess.Popen(cmd,env=os.environ.copy())
    try:
        rc=_CHILD.wait(timeout=timeout_seconds)
        return {'state':'EXIT','returncode':rc,'duration_seconds':round(time.time()-started,3)}
    except subprocess.TimeoutExpired:
        _CHILD.terminate()
        try:_CHILD.wait(timeout=8)
        except subprocess.TimeoutExpired:
            _CHILD.kill();_CHILD.wait()
        exc=TimeoutError(f'SCAN_CYCLE_TIMEOUT:{timeout_seconds}s')
        write_status(status,degraded_status(exc))
        return {'state':'TIMEOUT','returncode':124,'duration_seconds':round(time.time()-started,3)}
    finally:
        _CHILD=None


def main(argv=None):
    p=argparse.ArgumentParser(description='Self-healing supervisor for Robinhood Mint Radar')
    p.add_argument('--db',default=os.getenv('RADAR_DB','data/radar.sqlite'))
    p.add_argument('--status',default=os.getenv('RADAR_STATUS_PATH','public/status.json'))
    p.add_argument('--interval',type=float,default=float(os.getenv('RADAR_SCAN_INTERVAL','15')))
    p.add_argument('--cycle-timeout',type=float,default=float(os.getenv('RADAR_CYCLE_TIMEOUT_SECONDS','90')))
    args=p.parse_args(argv)
    if args.cycle_timeout<10:args.cycle_timeout=10
    for sig in (signal.SIGTERM,signal.SIGINT):
        try:signal.signal(sig,_handle_signal)
        except Exception:pass
    print(json.dumps({'supervisor':'STARTED','cycle_timeout_seconds':args.cycle_timeout,'interval_seconds':args.interval}),flush=True)
    while not _STOP:
        result=run_cycle(args.db,args.status,args.cycle_timeout)
        print(json.dumps({'supervisor_cycle':result}),flush=True)
        if _STOP:break
        deadline=time.time()+max(1.0,args.interval)
        while not _STOP and time.time()<deadline:time.sleep(min(1.0,max(0.0,deadline-time.time())))
    print(json.dumps({'supervisor':'STOPPED'}),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
