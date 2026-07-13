import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

// shadcn 标配 cn():clsx + tailwind-merge,处理冲突类名。
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
