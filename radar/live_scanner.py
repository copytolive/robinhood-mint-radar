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

    Every block is preserved in order. Expensive enrichment is delayed until
    catch-up is complete, checkpoints advance only after successful log scans,
    and readiness is measured in both elapsed chain time and an absolute block
    cap (important on Robinhood Chain where many blocks can arrive per second).
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

    def _lag_metrics(self,safe_block,processed_to):
        if safe_block is None or processed_to is None:
            return None,None
        blocks=max(0,int(safe_block)-int(processed_to))
        safe_ts=self.block_time(int(safe_block))
        cursor_ts=self.block_time(int(processed_to))
        seconds=max(0,int(safe_ts)-int(cursor_ts))
        return blocks,seconds

    def _lag_is_ready(self,blocks,seconds):
        return (
            blocks is not None and seconds is not None and
            blocks<=config.MAX_READY_LAG_BLOCKS and
            seconds<=config.MAX_READY_LAG_SECONDS
        )

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

        # Keep refreshing the safe tip until the cursor is fresh in *time*, not
        # merely within a tiny fixed block count. This also lets doctor/public
        # lookback scans tolerate a fast-moving sequencer without false failure.
        while ranges<max_ranges:
            while cursor<=safe and ranges<max_ranges:
                end=min(safe,cursor+chunk-1)
                self._scan_range_or_raise(cursor,end)
                self._checkpoint(end)
                processed_to=end
                cursor=end+1
                ranges+=1

            tip_now=self.rpc.block_number()
            safe_now=max(0,tip_now-config.CONFIRMATION_BLOCKS)
            tip,safe=tip_now,safe_now
            lag_blocks,lag_seconds=self._lag_metrics(safe,processed_to)
            if self._lag_is_ready(lag_blocks,lag_seconds):
                break
            cursor=processed_to+1

        if processed_to<first:
            processed_to=min(first,safe)

        status=self.build_status(tip,safe,first,processed_to,started)

        # Enrichment itself takes time. Refresh the chain tip after enrichment so
        # the published readiness reflects completion-time freshness.
        final_tip=self.rpc.block_number()
        final_safe=max(0,final_tip-config.CONFIRMATION_BLOCKS)
        lag_blocks,lag_seconds=self._lag_metrics(final_safe,processed_to)
        status.setdefault('chain',{})['latest_block']=final_tip
        status['chain']['safe_block']=final_safe
        try:
            status['chain']['latest_block_age_seconds']=max(0,int(time.time())-int(self.block_time(final_tip)))
        except Exception:
            pass
        scan=status.setdefault('scan',{})
        scan['from_block']=first
        scan['to_block']=processed_to
        scan['blocks_processed']=max(0,processed_to-first+1)
        scan['lag_blocks']=lag_blocks
        scan['lag_seconds']=lag_seconds
        return status
