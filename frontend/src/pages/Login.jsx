import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { formatApiError } from "@/lib/api";
import { Loader2 } from "lucide-react";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(email, password);
      nav("/dashboard", { replace: true });
    } catch (err) {
      setError(formatApiError(err.response?.data?.detail) || err.message || "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-[1fr_1.1fr]">
      <div className="flex flex-col justify-between p-10 lg:p-14 bg-white">
        <div>
          <div className="font-display text-2xl font-bold leading-none">Ambiance</div>
          <div className="font-display text-2xl font-bold leading-none text-[#0055FF]">Analytics</div>
          <div className="eyebrow mt-3">Seller Hub</div>
        </div>

        <div className="max-w-sm w-full mx-auto py-12">
          <h1 className="font-display text-3xl lg:text-4xl font-bold mb-2 tracking-tight">Sign in</h1>
          <p className="text-sm text-[#5E636E] mb-8">Access your multi-marketplace command center.</p>

          <form onSubmit={submit} className="space-y-5" data-testid="login-form">
            <div>
              <label className="eyebrow block mb-2">Email</label>
              <input
                type="email"
                required
                data-testid="login-email-input"
                className="in w-full"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@ambiancesticker.com"
              />
            </div>
            <div>
              <label className="eyebrow block mb-2">Password</label>
              <input
                type="password"
                required
                data-testid="login-password-input"
                className="in w-full"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
              />
            </div>
            {error && (
              <div className="text-sm text-[#FF2A2A] bg-[#FFEAEA] px-3 py-2" data-testid="login-error">{error}</div>
            )}
            <button
              type="submit"
              disabled={busy}
              data-testid="login-submit-button"
              className="btn-primary w-full flex items-center justify-center gap-2"
            >
              {busy && <Loader2 size={14} className="animate-spin" />} Sign in
            </button>
          </form>
        </div>
        <div className="text-xs text-[#5E636E]">© Ambiance Sticker · Multi-marketplace analytics</div>
      </div>
      <div
        className="hidden lg:block relative"
        style={{
          backgroundImage:
            "url(https://images.pexels.com/photos/577210/pexels-photo-577210.jpeg)",
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      >
        <div className="absolute inset-0 bg-black/30" />
        <div className="absolute bottom-10 left-10 right-10 text-white">
          <div className="eyebrow text-white/60">Real-time intelligence</div>
          <p className="font-display text-3xl xl:text-4xl font-bold mt-3 leading-tight max-w-md">
            Every channel, one truth. Track sales, margins and momentum across every marketplace you sell on.
          </p>
        </div>
      </div>
    </div>
  );
}
