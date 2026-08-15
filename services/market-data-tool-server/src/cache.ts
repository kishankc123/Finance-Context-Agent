interface Entry<T> {
  value: T;
  expiresAt: number;
}

/**
 * In-memory TTL cache. Swappable for Redis later (same get/set/stats shape)
 * without touching call sites — see README for the migration note.
 */
export class TtlCache<T> {
  private store = new Map<string, Entry<T>>();
  private hits = 0;
  private misses = 0;

  constructor(private ttlSeconds: number) {}

  get(key: string): T | undefined {
    const entry = this.store.get(key);
    if (!entry) {
      this.misses++;
      return undefined;
    }
    if (Date.now() > entry.expiresAt) {
      this.store.delete(key);
      this.misses++;
      return undefined;
    }
    this.hits++;
    return entry.value;
  }

  set(key: string, value: T): void {
    this.store.set(key, { value, expiresAt: Date.now() + this.ttlSeconds * 1000 });
  }

  stats() {
    const total = this.hits + this.misses;
    return {
      hits: this.hits,
      misses: this.misses,
      hitRate: total === 0 ? 0 : this.hits / total,
      size: this.store.size,
    };
  }
}
