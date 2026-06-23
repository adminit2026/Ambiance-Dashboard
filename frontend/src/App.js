import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/lib/auth";
import Login from "@/pages/Login";
import Layout from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import Marketplaces from "@/pages/Marketplaces";
import Products from "@/pages/Products";
import Prices from "@/pages/Prices";
import Customers from "@/pages/Customers";
import ProfitLoss from "@/pages/ProfitLoss";
import Orders from "@/pages/Orders";
import HeatMap from "@/pages/HeatMap";
import Uploads from "@/pages/Uploads";
import Settings from "@/pages/Settings";
import { Toaster } from "sonner";

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center text-sm text-[#5E636E]">Loading...</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function App() {
  return (
    <AuthProvider>
      <Toaster position="top-right" />
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/"
            element={
              <Protected>
                <Layout />
              </Protected>
            }
          >
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="marketplaces" element={<Marketplaces />} />
            <Route path="products" element={<Products />} />
            <Route path="prices" element={<Prices />} />
            <Route path="customers" element={<Customers />} />
            <Route path="profit-loss" element={<ProfitLoss />} />
            <Route path="orders" element={<Orders />} />
            <Route path="heatmap" element={<HeatMap />} />
            <Route path="uploads" element={<Uploads />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
