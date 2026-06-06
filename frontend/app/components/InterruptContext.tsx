"use client";
import { createContext, useContext, useRef, useState } from "react";

export interface PendingInterrupt {
  tool: string;
  resolve: (r: any) => void;
}

interface InterruptCtx {
  pending: PendingInterrupt | null;
  setPending: (p: PendingInterrupt | null) => void;
}

export const InterruptContext = createContext<InterruptCtx>({ pending: null, setPending: () => {} });
export const useInterruptContext = () => useContext(InterruptContext);

export function InterruptProvider({ children }: { children: React.ReactNode }) {
  const [pending, setPending] = useState<PendingInterrupt | null>(null);
  return (
    <InterruptContext.Provider value={{ pending, setPending }}>
      {children}
    </InterruptContext.Provider>
  );
}
