import unittest
from radar.relevance import evaluate_relevance

class RelevanceTests(unittest.TestCase):
    def test_position_manager_rejected(self):
        r=evaluate_relevance('ERC721','NonfungiblePositionManager','contract NonfungiblePositionManager { function tokenURI() external {} }')
        self.assertEqual(r['state'],'REJECT')
    def test_live_position_nft_names_rejected(self):
        for name in ('up Position NFT','Ekubo Ve33 Positions','Giga Positions'):
            with self.subTest(name=name):
                r=evaluate_relevance('ERC721',name,'contract GenericERC721 { function tokenURI() external {} }')
                self.assertEqual(r['state'],'REJECT')
    def test_liquidity_book_token_rejected(self):
        r=evaluate_relevance('ERC1155','Liquidity Book Token','contract LBPair { function uri(uint256) external view returns (string memory) {} }')
        self.assertEqual(r['state'],'REJECT')
    def test_seadrop_collectible_passes(self):
        r=evaluate_relevance('ERC721','ERC721SeaDropCloneable','contract ERC721SeaDropCloneable { function tokenURI() external {} }')
        self.assertEqual(r['state'],'PASS')
