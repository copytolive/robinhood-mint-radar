import unittest
from radar import config
class ReorgConfigTests(unittest.TestCase):
    def test_confirmations_enabled(self):self.assertGreaterEqual(config.CONFIRMATION_BLOCKS,1)
