import unittest
from radar.relevance import evaluate_relevance

class RelevanceTests(unittest.TestCase):
    def test_position_manager_rejected(self):
        r=evaluate_relevance('ERC721','NonfungiblePositionManager','contract NonfungiblePositionManager { function tokenURI() external {} }')
        self.assertEqual(r['state'],'REJECT')
    def test_seadrop_collectible_passes(self):
        r=evaluate_relevance('ERC721','ERC721SeaDropCloneable','contract ERC721SeaDropCloneable { function tokenURI() external {} }')
        self.assertEqual(r['state'],'PASS')
