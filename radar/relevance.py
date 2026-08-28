_DENY_NAME=('positionmanager','nonfungibleposition','liquidityposition','stakingposition','loanposition','debtposition','vaultposition','receipt','vestingposition','uniswap','algebra','camelot','clamm','lpposition','liquidity manager','position nft','positions','liquidity book token','lbpair')
_POSITIVE_NAME=('hoodsea','erc721seadrop','seadrop','erc721','erc1155','nft')
_POSITIVE_SOURCE=('tokenuri(','contracturi(','baseuri','erc721','erc1155')

def evaluate_relevance(standard,contract_name=None,source_text='',launch=None,market=None,interfaces=None):
    name=(contract_name or '').lower(); source=(source_text or '').lower(); reasons=[]
    if standard not in ('ERC721','ERC1155'): return {'state':'REJECT','reasons':['UNSUPPORTED_NFT_STANDARD'],'confidence':'HIGH'}
    for needle in _DENY_NAME:
        if needle in name:return {'state':'REJECT','reasons':[f'NON_COLLECTIBLE_NAME:{needle}'],'confidence':'HIGH'}
    if not launch:
        for needle,label in (('nonfungiblepositionmanager','NON_COLLECTIBLE_POSITION_MANAGER'),('positions(','POSITION_ACCOUNTING_SOURCE'),('liquidity(','LIQUIDITY_ACCOUNTING_SOURCE'),('lbpair','LIQUIDITY_BOOK_PAIR_SOURCE')):
            if needle in source and ('tokenuri' not in source or 'position' in source or needle=='lbpair'):reasons.append(label)
    if reasons:return {'state':'REJECT','reasons':sorted(set(reasons)),'confidence':'MEDIUM'}
    strong=False
    if launch:strong=True; reasons.append('KNOWN_LAUNCHPAD_COLLECTION')
    if any(x in name for x in _POSITIVE_NAME):strong=True; reasons.append('COLLECTIBLE_CONTRACT_NAME')
    if market and market.get('state')=='LIVE':strong=True; reasons.append('SECONDARY_MARKET_OBSERVED')
    expected='erc721' if standard=='ERC721' else 'erc1155'
    if interfaces and interfaces.get(expected) is True: strong=True; reasons.append('ERC165_STANDARD_CONFIRMED')
    if 'tokenuri(' in source or 'uri(' in source:reasons.append('NFT_METADATA_INTERFACE')
    if strong:return {'state':'PASS','reasons':reasons or ['NFT_COLLECTION_SIGNAL'],'confidence':'HIGH'}
    if contract_name and any(x in source for x in _POSITIVE_SOURCE):return {'state':'PASS','reasons':reasons+['VERIFIED_NFT_SOURCE'],'confidence':'MEDIUM'}
    return {'state':'REVIEW','reasons':reasons+['COLLECTIBLE_RELEVANCE_NOT_PROVEN'],'confidence':'LOW'}
