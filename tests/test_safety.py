import unittest
from radar.safety import analyze_source,evaluate_safety

class SafetyTests(unittest.TestCase):
    def test_owner_mint_requires_review(self):
        a=analyze_source('contract X { function mint(address a) external onlyOwner { _mint(a,1); } }')
        s=evaluate_safety({'verified':True,'proxy':False,'contract_name':'X',**a},'0x'+'1'*40)
        self.assertEqual(s['state'],'REVIEW')
        self.assertIn('OWNER_MINT_CAPABILITY',s['review_risks'])
    def test_selfdestruct_rejects(self):
        a=analyze_source('contract X { function bye() external { selfdestruct(payable(msg.sender)); } }')
        s=evaluate_safety({'verified':True,'proxy':False,'contract_name':'X',**a})
        self.assertEqual(s['state'],'REJECT')
