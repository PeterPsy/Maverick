/** Spread reconnects after an outage; a working snapshot resets the caller's attempt count. */
export function socketReconnectDelay(attempt: number, initialMs = 500, maximumMs = 30_000): number {
  const delay = Math.min(maximumMs, initialMs * 2 ** Math.min(attempt, 6));
  return Math.min(maximumMs, delay * (0.8 + Math.random() * 0.4));
}
