import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Standard shadcn class composition for app-owned components. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
