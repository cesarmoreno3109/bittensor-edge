import { NextResponse } from "next/server";
import { createClient } from "@libsql/client";

export const runtime = "nodejs";

export async function GET() {
  try {
    const url = process.env.TURSO_DB_URL;
    const token = process.env.TURSO_AUTH_TOKEN;

    if (!url || !token) {
      return NextResponse.json({
        error: "Missing env vars",
        TURSO_DB_URL: url ? "SET" : "MISSING",
        TURSO_AUTH_TOKEN: token ? "SET" : "MISSING",
      });
    }

    const db = createClient({ url, authToken: token });
    const result = await db.execute("SELECT COUNT(*) as cnt FROM tao_prices");
    return NextResponse.json({
      ok: true,
      count: result.rows[0]?.cnt,
      url_prefix: url.substring(0, 30),
    });
  } catch (e: unknown) {
    const err = e as Error;
    return NextResponse.json({
      error: err.message,
      stack: err.stack?.split("\n").slice(0, 5),
    }, { status: 500 });
  }
}
