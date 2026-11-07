// Stub registered in M2-01 so the library and viewer workstreams do not both edit routes.tsx.
// M2-04a replaces the body; keep the export name.
export function LibraryPage() {
  return (
    <main className="mx-auto max-w-3xl p-6" data-testid="library-stub">
      <h1 className="text-xl font-semibold">Documents</h1>
    </main>
  );
}
