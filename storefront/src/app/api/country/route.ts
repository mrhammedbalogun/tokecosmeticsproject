import { cookies } from "next/headers";
import { COUNTRY_COOKIE } from "@/lib/country";

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const code = typeof body.code === "string" ? body.code.trim().toUpperCase() : "";
  if (!code) return new Response(JSON.stringify({ detail: "code required" }), { status: 400 });
  // country is NOT httpOnly: it is not a secret and client UI reads it. 1 year.
  (await cookies()).set(COUNTRY_COOKIE, code, {
    httpOnly: false, sameSite: "lax", path: "/", maxAge: 60 * 60 * 24 * 365,
    secure: process.env.NODE_ENV === "production",
  });
  return new Response(JSON.stringify({ ok: true }), { status: 200 });
}
