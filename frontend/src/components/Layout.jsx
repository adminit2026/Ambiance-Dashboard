import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import LanguageToggle from "@/components/LanguageToggle";
import {
  LayoutDashboard,
  Store,
  Package,
  Tag,
  BookOpen,
  AlertTriangle,
  Undo2,
  Truck,
  Users,
  Receipt,
  Table2,
  Flame,
  UploadCloud,
  Settings as SettingsIcon,
  LogOut,
} from "lucide-react";

const NAV = [
  { to: "/dashboard", key: "nav.dashboard", icon: LayoutDashboard, id: "nav-dashboard" },
  { to: "/marketplaces", key: "nav.marketplaces", icon: Store, id: "nav-marketplaces" },
  { to: "/products", key: "nav.products", icon: Package, id: "nav-products" },
  { to: "/prices", key: "nav.prices", icon: Tag, id: "nav-prices" },
  { to: "/library", key: "nav.library", icon: BookOpen, id: "nav-library" },
  { to: "/loss-makers", key: "nav.loss_makers", icon: AlertTriangle, id: "nav-loss-makers" },
  { to: "/returns", key: "nav.returns", icon: Undo2, id: "nav-returns" },
  { to: "/amazon-delivery", key: "nav.amazon_delivery", icon: Truck, id: "nav-amazon-delivery" },
  { to: "/customers", key: "nav.customers", icon: Users, id: "nav-customers" },
  { to: "/profit-loss", key: "nav.profit_loss", icon: Receipt, id: "nav-profit-loss" },
  { to: "/orders", key: "nav.orders", icon: Table2, id: "nav-orders" },
  { to: "/heatmap", key: "nav.heatmap", icon: Flame, id: "nav-heat-map" },
  { to: "/uploads", key: "nav.uploads", icon: UploadCloud, id: "nav-uploads" },
  { to: "/settings", key: "nav.settings", icon: SettingsIcon, id: "nav-settings" },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const { t } = useT();
  const nav = useNavigate();

  const handleLogout = async () => {
    await logout();
    nav("/login");
  };

  return (
    <div className="min-h-screen flex">
      <aside className="sidebar w-[240px] shrink-0 flex flex-col" data-testid="sidebar">
        <div className="px-6 py-6 border-b border-[#2D313A]">
          <div className="font-display text-xl font-bold leading-tight">{t("app.title")}</div>
          <div className="font-display text-xl font-bold leading-tight text-[#0055FF]">{t("app.subtitle")}</div>
          <div className="eyebrow mt-2" style={{ color: "#7C8090" }}>{t("app.tagline")}</div>
        </div>
        <nav className="flex-1 py-4 overflow-y-auto">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              data-testid={n.id}
              className={({ isActive }) =>
                `flex items-center gap-3 px-6 py-2.5 text-sm transition-colors ${isActive ? "active" : ""}`
              }
            >
              <n.icon size={16} strokeWidth={1.5} />
              <span>{t(n.key)}</span>
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-[#2D313A] px-6 py-4">
          <div className="text-xs text-[#7C8090] mb-1">{t("auth.signed_in_as")}</div>
          <div className="text-sm font-medium truncate" data-testid="user-email">{user?.email}</div>
          <button
            className="mt-3 flex items-center gap-2 text-xs text-[#7C8090] hover:text-white transition-colors"
            onClick={handleLogout}
            data-testid="logout-button"
          >
            <LogOut size={14} /> {t("auth.signout")}
          </button>
        </div>
      </aside>
      <main className="flex-1 min-w-0 overflow-x-hidden">
        <div className="flex items-center justify-end px-8 py-3 border-b border-[#E5E7EB] bg-white" data-testid="top-bar">
          <LanguageToggle />
        </div>
        <Outlet />
      </main>
    </div>
  );
}
