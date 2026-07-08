import { Check } from 'lucide-react';
import { cn } from '@/lib/cn';

export interface Step {
  label: string;
}

type StepState = 'done' | 'active' | 'future';

interface StepIndicatorProps {
  steps:       Step[];
  currentStep: number; // 0-based
}

function getState(index: number, current: number): StepState {
  if (index < current) return 'done';
  if (index === current) return 'active';
  return 'future';
}

export function StepIndicator({ steps, currentStep }: StepIndicatorProps) {
  return (
    <nav aria-label="Upload progress" className="flex items-center">
      {steps.map((step, i) => {
        const state = getState(i, currentStep);
        const isLast = i === steps.length - 1;

        return (
          <div key={step.label} className="flex flex-1 flex-col items-center last:flex-none">
            <div className="flex w-full items-center">
              {/* Circle */}
              <div className="flex flex-col items-center">
                <div
                  className={cn(
                    'flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 transition-all duration-300',
                    state === 'done'   && 'border-indigo-600 bg-indigo-600',
                    state === 'active' && 'border-indigo-600 bg-white dark:bg-neutral-800',
                    state === 'future' && 'border-neutral-300 bg-white dark:border-neutral-600 dark:bg-neutral-800',
                  )}
                >
                  {state === 'done' ? (
                    <Check className="h-4 w-4 text-white" strokeWidth={2.5} />
                  ) : (
                    <span
                      className={cn(
                        'text-xs font-semibold',
                        state === 'active' && 'text-indigo-600',
                        state === 'future' && 'text-neutral-400',
                      )}
                    >
                      {i + 1}
                    </span>
                  )}
                </div>
              </div>

              {/* Connector line */}
              {!isLast && (
                <div className={cn(
                  'mx-1 flex-1 h-[2px] rounded-full transition-colors duration-500',
                  state === 'done' ? 'bg-indigo-500' : 'bg-neutral-200 dark:bg-neutral-700',
                )} />
              )}
            </div>

            {/* Label */}
            <span
              className={cn(
                'mt-2 text-[11px] font-medium whitespace-nowrap transition-colors duration-200',
                state === 'done'   && 'text-indigo-500',
                state === 'active' && 'text-indigo-700 dark:text-indigo-300',
                state === 'future' && 'text-neutral-400',
              )}
            >
              {step.label}
            </span>
          </div>
        );
      })}
    </nav>
  );
}
