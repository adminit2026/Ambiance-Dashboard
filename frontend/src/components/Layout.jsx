import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import {
  LayoutDashboard,
  Store,
  Package,
  Users,
  Receipt,
  Table2,
  Flame,
  UploadCloud,
  Settings as SettingsIcon,
  LogOut,
} from "lucide-react";

const NAV = [
  { to: "/dashboard", label: "Aggregate", icon: LayoutDashboard, id: "nav-dashboard" },
  { to: "/marketplaces", label: "Marketplaces", icon: Store, id: "nav-marketplaces" },
  { to: "/products", label: "Products", icon: Package, id: "nav-products" },
  { to: "/customers", label: "Customers", icon: Users, id: "nav-customers" },
  { to: "/profit-loss", label: "Profit & Loss", icon: Receipt, id: "nav-profit-loss" },
  { to: "/orders", label: "Orders", icon: Table2, id: "nav-orders" },
  { to: "/heatmap", label: "Heat Map", icon: Flame, id: "nav-heatmap" },
  { to: "/uploads", label: "Uploads", icon: UploadCloud, id: "nav-uploads" },
  { to: "/settings", label: "Settings", icon: SettingsIcon, id: "nav-settings" },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();

  const handleLogout = async () => {
    await logout();
    nav("/login");
  };

  return (
    <div className="min-h-screen flex">
      <aside className="sidebar w-[240px] shrink-0 flex flex-col" data-testid="sidebar">
        <div className="px-6 py-6 border-b border-[#2D313A]">
          <div className="font-display text-xl font-bold leading-tight">Ambiance</div>
          <div className="font-display text-xl font-bold leading-tight text-[#0055FF]">Analytics</div>
          <div className="eyebrow mt-2" style={{ color: "#7C8090" }}>Seller Hub</div>
        </div>
        <nav className="flex-1 py-4">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              data-testid={n.id}
              className={({ isActive }) =>
                `flex items-center gap-3 px-6 py-3 text-sm transition-colors ${isActive ? "active" : ""}`
              }
            >
              <n.icon size={16} strokeWidth={1.5} />
              <span>{n.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-[#2D313A] px-6 py-4">
          <div className="text-xs text-[#7C8090] mb-1">Signed in as</div>
          <div className="text-sm font-medium truncate" data-testid="user-email">{user?.email}</div>
          <button
            className="mt-3 flex items-center gap-2 text-xs text-[#7C8090] hover:text-white transition-colors"
            onClick={handleLogout}
            data-testid="logout-button"
          >
            <LogOut size={14} /> Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 min-w-0 overflow-x-hidden">
        <Outlet />
      </main>
    </div>
  );
}
