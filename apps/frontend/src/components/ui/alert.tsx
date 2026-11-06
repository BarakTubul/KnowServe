import { cva, type VariantProps } from 'class-variance-authority';
import * as React from 'react';
import { cn } from '@/lib/utils';

const alertVariants = cva('rounded-md border px-3 py-2 text-sm', {
  variants: {
    variant: {
      info: 'border-border bg-muted text-foreground',
      error: 'border-destructive text-destructive',
      success: 'border-success text-success',
    },
  },
  defaultVariants: { variant: 'info' },
});

export interface AlertProps
  extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof alertVariants> {}

/** Errors are announced (role="alert"); other messages are polite status updates. */
export function Alert({ className, variant, role, ...props }: AlertProps) {
  return (
    <div
      role={role ?? (variant === 'error' ? 'alert' : 'status')}
      className={cn(alertVariants({ variant }), className)}
      {...props}
    />
  );
}
