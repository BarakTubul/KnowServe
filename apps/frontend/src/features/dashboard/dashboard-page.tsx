import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuth } from '@/features/auth/auth-context';
import { DepartmentSelectorDialog } from '@/features/departments/department-selector';
import { RequireDepartment } from '@/features/departments/require-department';
import { CreateAccountPanel } from './create-account-panel';
import { DemoModeIndicator } from './demo-mode-indicator';

/** Minimal M1 landing screen: identity, department and the account actions. Content arrives in M2+. */
export function DashboardPage() {
  const { identity, logout, openDepartmentSelector } = useAuth();
  const [converted, setConverted] = useState(false);
  if (!identity) return null;
  const isDemo = identity.kind === 'demo';

  return (
    <main data-testid="dashboard-page" className="mx-auto flex max-w-3xl flex-col gap-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">KnowServe</h1>
        <div className="flex flex-wrap items-center gap-3">
          <DemoModeIndicator />
          <span data-testid="account-kind" className="text-sm text-muted-foreground">
            {isDemo ? 'Demo visitor' : 'Registered'}
            {identity.email ? ` (${identity.email})` : ''}
          </span>
          {identity.active_department && (
            <Button variant="outline" size="sm" onClick={openDepartmentSelector}>
              Change department
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => void logout()}>
            Sign out
          </Button>
        </div>
      </header>
      {converted && (
        <Alert variant="success" data-testid="registered-state">
          Your account is registered. Your Demo history and departments are kept.
        </Alert>
      )}
      <RequireDepartment>
        <Card>
          <CardHeader>
            <CardTitle>Active department</CardTitle>
          </CardHeader>
          <CardContent>
            <p data-testid="active-department" className="text-lg">
              {identity.active_department?.name}
            </p>
          </CardContent>
        </Card>
        <Link
          to="/documents"
          data-testid="library-link"
          className="self-start text-lg font-medium underline"
        >
          Browse documents
        </Link>
      </RequireDepartment>
      {isDemo && <CreateAccountPanel onConverted={() => setConverted(true)} />}
      <DepartmentSelectorDialog />
    </main>
  );
}
