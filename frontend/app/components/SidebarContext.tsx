"use client";
import { createContext, useContext } from "react";

export const SidebarContext = createContext<{
  open: boolean;
  toggle: () => void;
}>({ open: true, toggle: () => {} });

export function useSidebar() {
  return useContext(SidebarContext);
}
