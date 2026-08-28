import unittest
from unittest.mock import patch
from radar.cli import finalize_status


class StatusTimestampTests(unittest.TestCase):
    def test_generated_at_is_completion_time(self):
        status={'generated_at':100,'live_ready':'READY'}
        with patch('radar.cli.time.time',return_value=1000.9):
            out=finalize_status(status)
        self.assertIs(out,status)
        self.assertEqual(out['generated_at'],1000)
        self.assertEqual(out['live_ready'],'READY')
