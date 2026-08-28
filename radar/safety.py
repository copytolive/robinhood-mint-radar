import re

def analyze_source(source, proxy=False):
    low=(source or '').lower()
    hard=[]
    review=[]
    caps=[]
    if 'selfdestruct' in low:
        hard.append('SELFDESTRUCT_SOURCE')
    if 'tx.origin' in low:
        hard.append('TX_ORIGIN_AUTH')
    if 'delegatecall' in low:
        review.append('DELEGATECALL_SOURCE')
    if proxy:
        review.append('PROXY_CONTRACT')
    checks=[
      ('setmaxsupply','MUTABLE_MAX_SUPPLY'),
      ('setmintprice','MUTABLE_MINT_PRICE'),
      ('setbaseuri','MUTABLE_BASE_URI'),
      ('setcontracturi','MUTABLE_CONTRACT_URI'),
      ('setroyalty','MUTABLE_ROYALTY'),
      ('setdefaultroyalty','MUTABLE_ROYALTY'),
      ('pause(', 'PAUSABLE'),
      ('unpause(', 'PAUSABLE'),
      ('blacklist', 'BLACKLIST_CAPABILITY'),
      ('freeze', 'FREEZE_CAPABILITY'),
      ('upgradeto(', 'UPGRADEABLE'),
      ('upgradetoandcall(', 'UPGRADEABLE'),
      ('withdraw(', 'WITHDRAW_CAPABILITY'),
      ('sweep(', 'WITHDRAW_CAPABILITY'),
    ]
    for needle,label in checks:
        if needle in low:
            review.append(label)
    owner_mint = re.search(r'function\s+\w*mint\w*\s*\([^)]*\)[\s\S]{0,500}onlyowner', low)
    role_mint = re.search(r'function\s+\w*mint\w*\s*\([^)]*\)[\s\S]{0,500}(onlyrole|hasrole)', low)
    if owner_mint:
        review.append('OWNER_MINT_CAPABILITY')
    if role_mint:
        review.append('ROLE_MINT_CAPABILITY')
    if '.call{' in low or '.call(' in low:
        review.append('LOW_LEVEL_CALL_CAPABILITY')
    for cap in ('mint','burn','pause','blacklist','freeze','upgrade','withdraw'):
        if cap in low:
            caps.append(cap.upper())
    return {
      'hard_risks':sorted(set(hard)),
      'review_risks':sorted(set(review)),
      'capabilities':sorted(set(caps)),
    }

def evaluate_safety(verification, owner_address=None):
    hard=list(verification.get('hard_risks') or [])
    review=list(verification.get('review_risks') or [])
    verified=verification.get('verified')
    if verified is False:
        hard.append('UNVERIFIED_CONTRACT')
    elif verified is None:
        review.append('VERIFICATION_UNAVAILABLE')
    owner=(owner_address or '').lower()
    owner_active=bool(owner and owner != '0x'+'0'*40)
    if owner_active and any(x in review for x in ('OWNER_MINT_CAPABILITY','MUTABLE_MAX_SUPPLY','UPGRADEABLE')):
        review.append('ACTIVE_PRIVILEGED_OWNER')
    if hard:
        state='REJECT'; confidence='HIGH'
    elif review:
        state='REVIEW'; confidence='MEDIUM'
    else:
        state='PASS'; confidence='HIGH'
    return {
      'state':state,
      'verified':verified,
      'proxy':verification.get('proxy'),
      'contract_name':verification.get('contract_name'),
      'owner':owner_address,
      'owner_active':owner_active,
      'hard_risks':sorted(set(hard)),
      'review_risks':sorted(set(review)),
      'capabilities':verification.get('capabilities') or [],
      'confidence':confidence,
    }
