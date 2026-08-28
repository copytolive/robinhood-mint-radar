"""Deterministic EVM event topics and function selectors.

These are keccak256(signature) constants. They must never require an RPC
round-trip: asking a public node to compute constants on every scanner startup
adds latency and makes readiness depend on an unnecessary network call.
"""

TOPICS={
    'erc721':'0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef',
    'erc1155_single':'0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62',
    'erc1155_batch':'0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07e595d983b8c0526c8f7fb',
    'hoodsea_launch':'0x107c8d1b9a64f45bbe60918da1ac5b35998371338b84776cfdc6ddaaee66e3fd',
    'hoodsea_sold':'0x2820044bbebd591ee7d08b7d81dd01945a1a32706da693a946e532d6d9884258',
    'seaport_fulfilled':'0x9d9af8e38d66c62e2c12f0225249fd9d721c54b83f48d9352c97c6cacdcb6f31',
}

SELECTORS={
    'supports':'0x01ffc9a7',
    'totalSupply':'0x18160ddd',
    'totalMinted':'0xa2309ff8',
    'maxSupply':'0xd5abeb01',
    'mintPrice':'0x6817c76c',
    'mintPriceWei':'0xcb2c9722',
    'name':'0x06fdde03',
    'symbol':'0x95d89b41',
    'info':'0x370158ea',
    'owner':'0x8da5cb5b',
}
