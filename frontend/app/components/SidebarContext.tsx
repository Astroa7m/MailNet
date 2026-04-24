"use client";
import { createContext, useContext } from "react";

export interface AppUser {
  name: string;
  email: string;
  picture: string;
  providers: string[];
}

interface SidebarContextValue {
  open: boolean;
  toggle: () => void;
  user: AppUser | null;
  setUser: (u: AppUser | null) => void;
}

export const SidebarContext = createContext<SidebarContextValue>({
  open: true,
  toggle: () => {},
  user: null,
  setUser: () => {},
});

export function useSidebar() {
  return useContext(SidebarContext);
}
