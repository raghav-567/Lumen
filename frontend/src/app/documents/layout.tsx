'use client';

import { useState } from 'react';
import Sidebar from '@/components/Sidebar';

export default function Layout({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <>
      <div className="mesh-background">
        <div className="mesh-orb" />
        <div className="mesh-orb" />
      </div>
      <div className="app-layout">
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
        <main className={`main-content ${collapsed ? 'sidebar-collapsed' : ''}`}>
          {children}
        </main>
      </div>
    </>
  );
}
