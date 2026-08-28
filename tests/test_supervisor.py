import json
import os
import tempfile
import unittest
from unittest.mock import patch

from radar import supervisor


class _TimeoutProc:
    def __init__(self,*args,**kwargs):self.terminated=False;self.killed=False
    def wait(self,timeout=None):
        import subprocess
        if self.killed or self.terminated:return 0
        raise subprocess.TimeoutExpired(['radar'],timeout)
    def poll(self):return None
    def terminate(self):self.terminated=True
    def kill(self):self.killed=True


class _ExitProc:
    def __init__(self,*args,**kwargs):pass
    def wait(self,timeout=None):return 0
    def poll(self):return 0


class SupervisorTests(unittest.TestCase):
    def test_timeout_writes_fail_closed_status_and_returns_124(self):
        with tempfile.TemporaryDirectory() as d:
            status=os.path.join(d,'status.json')
            with patch('radar.supervisor.subprocess.Popen',_TimeoutProc):
                out=supervisor.run_cycle(os.path.join(d,'db.sqlite'),status,10)
            self.assertEqual(out['state'],'TIMEOUT')
            self.assertEqual(out['returncode'],124)
            with open(status) as fh:data=json.load(fh)
            self.assertEqual(data['live_ready'],'NOT_READY')
            self.assertEqual(data['wallet_execution'],'MANUAL_ONLY')
            self.assertEqual(data['manual_packages'],[])

    def test_successful_cycle_returns_without_synthetic_status(self):
        with tempfile.TemporaryDirectory() as d:
            status=os.path.join(d,'status.json')
            with patch('radar.supervisor.subprocess.Popen',_ExitProc):
                out=supervisor.run_cycle(os.path.join(d,'db.sqlite'),status,10)
            self.assertEqual(out['state'],'EXIT')
            self.assertEqual(out['returncode'],0)
            self.assertFalse(os.path.exists(status))


if __name__=='__main__':unittest.main()
