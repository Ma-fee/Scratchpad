# Task 12: Cache Memory Management and LRU Eviction - Learnings

## Implementation Approach
- Used `collections.OrderedDict` instead of regular `dict` for LRU tracking
- `move_to_end()` method moves items to MRU position
- First item in OrderedDict is always LRU for eviction

## Memory Estimation
- Formula: sum(len(s) for s in entries) + (overhead per string * count) + entry_overhead
- Conservative estimates prevent memory overflow
- String overhead in Python ~49 bytes per string object
- Entry overhead ~200 bytes for dict entry + CacheEntry object

## Key Design Decisions
1. Track `accessed_at` in CacheEntry alongside `created_at`
2. Stats tracked real-time in `CacheStats` dataclass
3. Memory eviction triggered before size-based eviction
4. Entries too large for memory limit are simply not cached (graceful degradation)

## Testing Strategy
- Unit tests for each component (stats, LRU, memory)
- QA scenario test verifying end-to-end behavior
- Property-based verification (hit_rate calculation)

## Backward Compatibility
- All new parameters have sensible defaults
- Existing tests continue to pass
- `OrderedDict` is API-compatible with `dict`
