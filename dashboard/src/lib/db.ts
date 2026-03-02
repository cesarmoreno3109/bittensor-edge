import { createClient, type Client } from "@libsql/client";

let _db: Client | null = null;

export function getDb(): Client {
  if (!_db) {
    const url = process.env.TURSO_DB_URL;
    const authToken = process.env.TURSO_AUTH_TOKEN;
    if (!url || !authToken) {
      throw new Error("TURSO_DB_URL and TURSO_AUTH_TOKEN must be set");
    }
    _db = createClient({ url, authToken });
  }
  return _db;
}

// Lazy accessor — won't crash at import time during build
export const db = new Proxy({} as Client, {
  get(_target, prop) {
    return (getDb() as unknown as Record<string | symbol, unknown>)[prop];
  },
});
