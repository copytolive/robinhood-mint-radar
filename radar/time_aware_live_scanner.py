from . import config
from .bounded_fast_live_scanner import BoundedFastLiveRadarScanner
from .rpc import RPCError


class TimeAwareLiveRadarScanner(BoundedFastLiveRadarScanner):
    """Bounded live scanner whose outage recovery follows readiness time too.

    Robinhood Chain can advance enough blocks that a cursor remains below the
    absolute block cap while already being older than the 60-second readiness
    contract. Continuous local scanning therefore rebases when either the block
    backlog or the chain-time backlog is stale. Skipped ranges are recorded by
    the inherited historical-gap machinery and are never treated as analyzed.
    """

    def _runtime_rebase_if_stale(self,public_lookback=None):
        if public_lookback is not None:
            return
        last=self.db.last_block()
        if last is None:
            return

        tip=self.rpc.block_number()
        safe=max(0,tip-config.CONFIRMATION_BLOCKS)
        lag_blocks=max(0,safe-int(last))
        block_threshold=max(int(config.RUNTIME_REBASE_LAG_BLOCKS),int(config.INITIAL_LOOKBACK_BLOCKS))
        time_threshold=int(getattr(config,'RUNTIME_REBASE_LAG_SECONDS',config.MAX_READY_LAG_SECONDS))
        # Never let the recovery threshold be looser than the readiness contract.
        time_threshold=min(time_threshold,int(config.MAX_READY_LAG_SECONDS))

        lag_seconds=None
        if lag_blocks>0:
            try:
                lag_seconds=max(0,int(self.block_time(safe))-int(self.block_time(int(last))))
            except Exception as exc:
                # If age cannot be proven, preserve the existing block-based
                # behavior. Readiness later remains fail-closed on unknown age.
                self._diag('LIVE_RECOVERY','RUNTIME_LAG_TIME_UNAVAILABLE',exc)

        block_stale=lag_blocks>block_threshold
        time_stale=lag_seconds is not None and lag_seconds>time_threshold
        if not block_stale and not time_stale:
            return

        new_first=max(0,safe-config.INITIAL_LOOKBACK_BLOCKS+1)
        checkpoint=max(0,new_first-1)
        gap_from=int(last)+1
        gap_to=checkpoint
        if gap_to>=gap_from:
            self._record_historical_gap(gap_from,gap_to)

        block=self.rpc.block(checkpoint) or {}
        block_hash=block.get('hash')
        if not block_hash:
            raise RPCError(f'RUNTIME_REBASE_HASH_UNAVAILABLE:{checkpoint}')

        self.db.set_meta('last_block_hash',block_hash)
        self.db.set_meta('last_block',checkpoint)
        detail=f'lag_blocks={lag_blocks}; lag_seconds={lag_seconds}; gap={gap_from}-{gap_to}; resume={new_first}'
        self._diag('LIVE_RECOVERY','RUNTIME_CURSOR_REBASED',detail)
        self._stage(
            'RUNTIME_REBASE',
            lag_blocks=lag_blocks,
            lag_seconds=lag_seconds,
            block_threshold=block_threshold,
            time_threshold=time_threshold,
            gap_from=gap_from,
            gap_to=gap_to,
            resume_from=new_first,
        )
