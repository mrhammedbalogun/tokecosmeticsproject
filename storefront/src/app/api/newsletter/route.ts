import { apiFetch, ApiError } from "@/lib/api";

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const email = typeof body.email === "string" ? body.email.trim() : "";
  if (!email || !email.includes("@")) return json({ email: ["Enter a valid email."] }, 400);

  // Forward the caller's IP so Django's per-IP throttle counts real users, not our
  // server (see Plan-12 D5; prod must trust X-Forwarded-For — Plan-02 note).
  const ip = req.headers.get("x-forwarded-for") ?? "";
  try {
    const out = await apiFetch("/newsletter/", {
      method: "POST",
      body: { email, source: body.source ?? "footer" },
      headers: ip ? { "X-Forwarded-For": ip } : {},
    });
    return json(out, 201);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
