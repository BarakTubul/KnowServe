import { useId } from 'react';
import type { Department } from '@/lib/api/client';

interface DepartmentChecklistProps {
  legend: string;
  departments: Department[];
  selected: readonly string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
  /** Describes the group to assistive technology, for example the error message. */
  describedBy?: string | undefined;
}

/** A labelled checkbox group of departments. Nothing is preselected here; callers decide (OPEN-16). */
export function DepartmentChecklist({
  legend,
  departments,
  selected,
  onChange,
  disabled = false,
  describedBy,
}: DepartmentChecklistProps) {
  const prefix = useId();
  function toggle(id: string, checked: boolean) {
    onChange(checked ? [...selected, id] : selected.filter((current) => current !== id));
  }
  return (
    <fieldset className="flex flex-col gap-2" aria-describedby={describedBy} disabled={disabled}>
      <legend className="text-sm font-medium">{legend}</legend>
      {departments.map((department) => {
        const id = `${prefix}-${department.id}`;
        return (
          <div key={department.id} className="flex items-center gap-2 text-sm">
            <input
              id={id}
              type="checkbox"
              checked={selected.includes(department.id)}
              onChange={(event) => toggle(department.id, event.target.checked)}
            />
            <label htmlFor={id}>{department.name}</label>
          </div>
        );
      })}
    </fieldset>
  );
}
