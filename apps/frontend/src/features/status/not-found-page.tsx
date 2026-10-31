import { Link } from 'react-router-dom';

export function NotFoundPage() {
  return (
    <main data-testid="not-found-page" className="mx-auto max-w-xl p-6">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="mt-2 text-muted-foreground">The page you asked for does not exist.</p>
      <Link to="/" className="mt-4 inline-block text-primary underline">
        Back to status
      </Link>
    </main>
  );
}
