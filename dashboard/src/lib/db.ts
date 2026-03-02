import { createClient } from "@libsql/client";

function makeDb() {
  const url = process.env.TURSO_DB_URL;
  const authToken = process.env.TURSO_AUTH_TOKEN;
  if (!url || !authToken) {
    throw new Error("Missing TURSO_DB_URL or TURSO_AUTH_TOKEN");
  }
  return createClient({ url, authToken });
}

// Lazy singleton
let _db: ReturnType<typeof createClient> | null = null;

export function getDb() {
  if (!_db) _db = makeDb();
  return _db;
}
