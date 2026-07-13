import * as React from 'react';
import { cn } from '@/lib/utils';

// 重新导出 Button 组件,允许从 '@/components/ui/primitives' 一处拿全 UI 基元。
export { Button } from './button';

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('rounded-lg border border-border bg-card text-card-foreground shadow-sm', className)} {...props} />
  ),
);
Card.displayName = 'Card';

export const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('flex flex-col space-y-1.5 p-4', className)} {...props} />
  ),
);
CardHeader.displayName = 'CardHeader';

export const CardTitle = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h3 ref={ref as React.Ref<HTMLHeadingElement>} className={cn('text-base font-semibold leading-none', className)} {...props} />
  ),
);
CardTitle.displayName = 'CardTitle';

export const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('p-4 pt-0', className)} {...props} />
  ),
);
CardContent.displayName = 'CardContent';

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        'flex h-8 w-full rounded-md border border-border bg-background px-2 py-1 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 disabled:opacity-50',
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = 'Input';
