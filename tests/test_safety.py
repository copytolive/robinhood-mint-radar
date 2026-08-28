import unittest
from radar.safety import analyze_source,evaluate_safety

class SafetyTests(unittest.TestCase):
    def test_owner_mint_requires_review(self):
        a=analyze_source('contract X { function mint(address a) external onlyOwner { _mint(a,1); } }')
        s=evaluate_safety({'verified':True,'proxy':False,'contract_name':'X',**a},'0x'+'1'*40)
        self.assertEqual(s['state'],'REVIEW'); self.assertIn('OWNER_MINT_CAPABILITY',s['review_risks'])
    def test_selfdestruct_rejects(self):
        a=analyze_source('contract X { function bye() external { selfdestruct(payable(msg.sender)); } }')
        self.assertEqual(evaluate_safety({'verified':True,'proxy':False,'contract_name':'X',**a})['state'],'REJECT')
    def test_tx_origin_presence_is_review_not_automatic_reject(self):
        a=analyze_source('contract X { function x() view returns(address){ return tx.origin; } }')
        self.assertNotIn('TX_ORIGIN_AUTH',a['hard_risks']); self.assertIn('TX_ORIGIN_PRESENT',a['review_risks'])
    def test_tx_origin_auth_is_reject(self):
        a=analyze_source('contract X { function x() external { require(tx.origin == owner); } }')
        self.assertIn('TX_ORIGIN_AUTH',a['hard_risks'])
