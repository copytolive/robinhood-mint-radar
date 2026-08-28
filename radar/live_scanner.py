import time
from . import config
from .rpc import RPCError
from .scanner import RadarScanner as BaseRadarScanner


_CRITICAL_LOG_FAILURES={
    'ERC721_LOG_SCAN_FAILED',
    'ERC1155_SINGLE_SCAN_FAILED',
    'ERC1155_BATCH_SCAN_FAILED',
    'HOODSEA_LAUNCH_SCAN_FAILED',
    'HOODSEA_NFTSOLD_SCAN_FAILED',
    'SEAPORT_LOG_SCAN_FAILED',
}


class LiveRadarScanner(BaseRadarScanner):
    """Continuous scanner that must catch its durable cursor up to the live tip.

    The original scanner enriched candidates after every small cursor advance.
    On a fast L2 that let block production outrun the scanner. This subclass
    preserves every block in order, checkpoints each successful range, delays
    expensive enrichment until catch-up is complete, and refuses to advance a
    checkpoint when a critical log family failed.
    """

    def _scan_range_or_raise(self,from_block,to_block):
        before=len(self.diag)
        added=super().scan_logs(from_block,to_block)
        failures=[d for d in self.diag[before:] if d.get('reason') in _CRITICAL_LOG_FAILURES]
        if failures:
            reasons=','.join(sorted({d.get('reason') for d in failures}))
            raise RPCError(f'CRITICAL_LOG_SCAN_FAILED:{from_block}-{to_block}:{reasons}')
        return added

    def _checkpoint(self,block_number):
        bh=(self.rpc.block(block_number) or {}).get('hash')
        if not bh:
            raise RPCError(f'CHECKPOINT_BLOCK_HASH_UNAVAILABLE:{block_number}')
        # Hash first, block number second. If the process dies between writes,
        # the previous last_block remains conservative rather than skipping.
        self.db.set_meta('last_block_hash',bh)
        self.db.set_meta('last_block',block_number)

    def _verify_checkpoint(self,last,stored_hash):
        if last is None or not stored_hash:
            return last
        live_hash=(self.rpc.block(last) or {}).get('hash')
        if not live_hash:
            raise RPCError(f'CHECKPOINT_HASH_VERIFY_UNAVAILABLE:{last}')
        if live_hash.lower()!=stored_hash.lower():
            self._diag('REORG','CHECKPOINT_HASH_MISMATCH',f'{last}')
            rewind=max(0,last-config.REORG_REWIND_BLOCKS)
            rewind_hash=(self.rpc.block(rewind) or {}).get('hash')
            if not rewind_hash:
                raise RPCError(f'REORG_REWIND_HASH_UNAVAILABLE:{rewind}')
            self.db.set_meta('last_block_hash',rewind_hash)
            self.db.set_meta('last_block',rewind)
            return rewind
        return last

    def scan_once(self,public_lookback=None):
        started=time.time();self.diag=[];self._init_signatures()
        chain=self.rpc.chain_id()
        if chain!=config.CHAIN_ID:
            raise RPCError(f'WRONG_CHAIN_ID:{chain}')

        tip=self.rpc.block_number()
        safe=max(0,tip-config.CONFIRMATION_BLOCKS)
        last=self.db.last_block()
        stored_hash=self.db.get_meta('last_block_hash')
        last=self._verify_checkpoint(last,stored_hash)

        if public_lookback is not None:
            first=max(0,safe-public_lookback+1)
        elif last is None:
            first=max(0,safe-config.INITIAL_LOOKBACK_BLOCKS+1)
        else:
            first=last+1
        if first>safe:
            first=safe

        cursor=first
        processed_to=first-1
        ranges=0
        max_ranges=50
        chunk=max(1,min(config.CHUNK_BLOCKS,config.MAX_CATCHUP_BLOCKS))

        while True:
            while cursor<=safe:
                end=min(safe,cursor+chunk-1)
                self._scan_range_or_raise(cursor,end)
                self._checkpoint(end)
                processed_to=end
                cursor=end+1
                ranges+=1
                if ranges>=max_ranges:
                    break

            # Public one-shot snapshots intentionally inspect one explicit tip
            # window. Continuous/local mode refreshes the target until genuinely
            # near the latest safe tip.
            if public_lookback is not None or ranges>=max_ranges:
                break

            tip_now=self.rpc.block_number()
            safe_now=max(0,tip_now-config.CONFIRMATION_BLOCKS)
            lag=max(0,safe_now-processed_to)
            tip,safe=tip_now,safe_now
            if lag<=config.MAX_READY_LAG_BLOCKS:
                break
            cursor=processed_to+1

        # Refresh once more so readiness compares the processed cursor with a
        # current tip, not the tip captured before a long catch-up.
        tip=self.rpc.block_number()
        safe=max(0,tip-config.CONFIRMATION_BLOCKS)
        if processed_to<first:
            processed_to=min(first,safe)

        return self.build_status(tip,safe,first,processed_to,started)
