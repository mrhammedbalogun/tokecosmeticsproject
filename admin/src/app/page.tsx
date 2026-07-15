export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 bg-neutral-100 px-6">
      <div className="w-full max-w-sm rounded-xl border border-neutral-200 bg-white p-8 text-center shadow-sm">
        <h1 className="text-2xl font-semibold tracking-tight text-neutral-900">
          Toke Admin
        </h1>
        <p className="mt-2 text-sm text-neutral-500">
          Sign in to the management portal.
        </p>
        <button
          type="button"
          disabled
          className="mt-6 w-full rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white opacity-60"
        >
          Sign in (coming soon)
        </button>
      </div>
    </main>
  );
}
