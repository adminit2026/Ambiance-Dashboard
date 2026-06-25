import { useT } from "@/lib/i18n";

const FLAGS = {
  en: "🇬🇧",
  fr: "🇫🇷",
};

export default function LanguageToggle() {
  const { lang, setLang } = useT();
  return (
    <div className="inline-flex items-center gap-1 border border-[#E5E7EB] bg-white" data-testid="language-toggle">
      {["en", "fr"].map((l) => (
        <button
          key={l}
          onClick={() => setLang(l)}
          className={`px-2.5 py-1.5 text-xs font-medium transition-colors ${
            lang === l ? "bg-[#111215] text-white" : "text-[#5E636E] hover:bg-[#FAFAFB]"
          }`}
          data-testid={`lang-${l}`}
          title={l === "en" ? "English" : "Français"}
        >
          <span className="text-sm leading-none">{FLAGS[l]}</span>{" "}
          <span className="uppercase tracking-wider">{l}</span>
        </button>
      ))}
    </div>
  );
}
