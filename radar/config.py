import os

CHAIN_ID=4663
CHAIN_HEX=hex(CHAIN_ID)
DEFAULT_RPC_URL=os.getenv('RH_RPC_URL','https://rpc.mainnet.chain.robinhood.com').strip()
# Robinhood documents the public RPC as rate-limited and not production-grade.
# Keep it primary, but allow verified read-only fallbacks so one endpoint reset
# cannot stall the scanner. Custom fallbacks may be supplied as comma-separated
# RH_RPC_FALLBACK_URLS; an empty value disables fallbacks.
_DEFAULT_RPC_FALLBACKS='https://rpc.nodeflare.app/robinhood/public,https://robinhood-mainnet-rpc.blockreq.com/v1/rpc/public'
_raw_fallbacks=os.getenv('RH_RPC_FALLBACK_URLS',_DEFAULT_RPC_FALLBACKS)
RPC_FALLBACK_URLS=tuple(x.strip() for x in _raw_fallbacks.split(',') if x.strip() and x.strip()!=DEFAULT_RPC_URL)
RPC_URLS=(DEFAULT_RPC_URL,)+RPC_FALLBACK_URLS
BLOCKSCOUT_API=os.getenv('BLOCKSCOUT_API','https://robinhoodchain.blockscout.com/api')
BLOCKSCOUT_V2=os.getenv('BLOCKSCOUT_V2','https://robinhoodchain.blockscout.com/api/v2')
HOODSEA_LAUNCHPAD='0xa1e9DAB10a4DED224c090c73B09b6658Cc69331b'
HOODSEA_SITE='https://hoodsea.com/'
SEAPORT_16=os.getenv('SEAPORT_16','0x0000000000000068F116a894984e2DB1123eB395')
ZERO_TOPIC='0x'+('0'*64)
TRANSFER_TOPIC='0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
DEFAULT_DB=os.getenv('RADAR_DB','data/radar.sqlite')
SCAN_INTERVAL=float(os.getenv('RADAR_SCAN_INTERVAL','15'))
INITIAL_LOOKBACK_BLOCKS=int(os.getenv('RADAR_INITIAL_LOOKBACK_BLOCKS','120'))
# Robinhood Chain is a high-throughput L2. A 60-block cursor advances too slowly
# once contract/market enrichment is included, so continuous scans use a much
# larger bounded catch-up window while preserving every block in sequence.
CHUNK_BLOCKS=int(os.getenv('RADAR_CHUNK_BLOCKS','5000'))
MAX_CATCHUP_BLOCKS=int(os.getenv('RADAR_MAX_CATCHUP_BLOCKS','5000'))
# Readiness is primarily time-based because this chain can advance many blocks
# per second. The block cap remains as an absolute sanity/fail-closed guard.
MAX_READY_LAG_BLOCKS=int(os.getenv('RADAR_MAX_READY_LAG_BLOCKS','2000'))
MAX_READY_LAG_SECONDS=int(os.getenv('RADAR_MAX_READY_LAG_SECONDS','60'))
CONFIRMATION_BLOCKS=int(os.getenv('RADAR_CONFIRMATION_BLOCKS','10'))
REORG_REWIND_BLOCKS=int(os.getenv('RADAR_REORG_REWIND_BLOCKS','120'))
MAX_CANDIDATES=int(os.getenv('RADAR_MAX_CANDIDATES','20'))
OPENSea_API_KEY=os.getenv('OPENSEA_API_KEY','').strip()
OPENSEA_CHAIN=os.getenv('OPENSEA_CHAIN','robinhood')
STATUS_PATH=os.getenv('RADAR_STATUS_PATH','public/status.json')
OBSERVATION_RETENTION_DAYS=int(os.getenv('RADAR_OBSERVATION_RETENTION_DAYS','30'))
EVENT_RETENTION_DAYS=int(os.getenv('RADAR_EVENT_RETENTION_DAYS','90'))
BACKUP_INTERVAL_SECONDS=int(os.getenv('RADAR_BACKUP_INTERVAL_SECONDS','86400'))
BACKUP_KEEP=int(os.getenv('RADAR_BACKUP_KEEP','7'))
