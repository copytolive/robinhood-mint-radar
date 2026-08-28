import os

CHAIN_ID = 4663
CHAIN_HEX = hex(CHAIN_ID)
DEFAULT_RPC_URL = os.getenv('RH_RPC_URL', 'https://rpc.mainnet.chain.robinhood.com')
BLOCKSCOUT_API = os.getenv('BLOCKSCOUT_API', 'https://robinhoodchain.blockscout.com/api')
HOODSEA_LAUNCHPAD = '0xa1e9DAB10a4DED224c090c73B09b6658Cc69331b'
ZERO_TOPIC = '0x' + ('0' * 64)
TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
DEFAULT_DB = os.getenv('RADAR_DB', 'data/radar.sqlite')
SCAN_INTERVAL = float(os.getenv('RADAR_SCAN_INTERVAL', '15'))
INITIAL_LOOKBACK_BLOCKS = int(os.getenv('RADAR_INITIAL_LOOKBACK_BLOCKS', '120'))
CHUNK_BLOCKS = int(os.getenv('RADAR_CHUNK_BLOCKS', '60'))
MAX_CANDIDATES = int(os.getenv('RADAR_MAX_CANDIDATES', '20'))
OPENSea_API_KEY = os.getenv('OPENSEA_API_KEY', '').strip()
OPENSEA_CHAIN = os.getenv('OPENSEA_CHAIN', 'robinhood')
STATUS_PATH = os.getenv('RADAR_STATUS_PATH', 'public/status.json')
