import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cn } from '@/lib/utils';

type Variant = 'default' | 'ghost' | 'outline' | 'destructive' | 'secondary';
const variantClass: Record<Variant, string> = {
  default: 'bg-primary text-primary-foreground hover:opacity-90',
  ghost: 'hover:bg-muted text-foreground',
  outline: 'border border-border bg-background hover:bg-muted',
  destructive: 'bg-red-600 text-white hover:bg-red-700',
  secondary: 'bg-muted text-foreground hover:opacity-90',
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'default', asChild, ...props }, ref) => {
    const Comp: React.ElementType = asChild ? Slot : 'button';
    return (
      <Comp
        ref={ref as React.Ref<HTMLButtonElement>}
        className={cn(
          'inline-flex items-center justify-center gap-1 rounded-md px-3 py-1.5 text-sm font-medium transition disabled:opacity-50 disabled:pointer-events-none focus:outline-none focus:ring-2 focus:ring-primary/40',
          variantClass[variant],
          className,
        )}
        {...props}
      />
    );
  },
);
Button.displayName = 'Button';
