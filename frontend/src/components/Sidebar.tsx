'use client';

import { usePathname } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api';
import {
  LayoutDashboard,
  FileText,
  Bell,
  Search,
  Network,
  LogOut,
  ChevronLeft,
  Zap,
} from 'lucide-react';

const navItems = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/documents', label: 'Documents', icon: FileText },
  { href: '/alerts', label: 'Alerts', icon: Bell, hasNotification: true },
  { href: '/search', label: 'Search', icon: Search },
  { href: '/graph', label: 'Knowledge Graph', icon: Network },
];

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname();

  const getInitials = () => {
    if (typeof window === 'undefined') return 'U';
    return 'U';
  };

  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      {/* Header */}
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">
            <Zap />
          </div>
          <span className="sidebar-logo-text">KnowledgeDrift</span>
        </div>
        <button
          className="sidebar-collapse-btn"
          onClick={onToggle}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <ChevronLeft size={14} />
        </button>
      </div>

      {/* User area */}
      <div className="sidebar-user">
        <div className="sidebar-avatar">{getInitials()}</div>
        <div className="sidebar-user-info">
          <div className="sidebar-user-name">User</div>
          <div className="sidebar-user-role">Admin</div>
        </div>
      </div>

      {/* Navigation */}
      <div className="sidebar-section-label">Navigation</div>
      <nav className="sidebar-nav">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href ||
            (item.href !== '/dashboard' && pathname?.startsWith(item.href));

          return (
            <Link
              key={item.href}
              href={item.href}
              className={`sidebar-link ${isActive ? 'active' : ''}`}
            >
              <Icon className="sidebar-icon" />
              <span className="sidebar-link-label">{item.label}</span>
              {item.hasNotification && (
                <span className="notification-dot" />
              )}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="sidebar-divider" />
      <Link
        href="/login"
        className="sidebar-link"
        onClick={() => {
          api.clearToken();
        }}
      >
        <LogOut className="sidebar-icon" />
        <span className="sidebar-link-label">Logout</span>
      </Link>
    </aside>
  );
}
