"use client";

import { useEffect, useState } from "react";

import { ApiError, apiRequest } from "@/lib/api";
import { AssistantWorkspace } from "@/components/assistant-workspace";

type User = {
  id: string;
  email: string;
  display_name: string;
};

type Gate = "loading" | "setup" | "login" | "authenticated" | "unavailable";
type Theme = "light" | "dark";

const THEME_STORAGE_KEY = "finance-ai-theme";

export function AppShell() {
  const [gate, setGate] = useState<Gate>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [bootstrapToken, setBootstrapToken] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [setupAvailable, setSetupAvailable] = useState(true);
  const [bootstrapTokenRequired, setBootstrapTokenRequired] = useState(false);
  const [mfaRequired, setMfaRequired] = useState(false);
  const [messageKind, setMessageKind] = useState<"error" | "success">("error");
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
    const initialTheme: Theme = savedTheme === "dark" ? "dark" : "light";
    document.documentElement.dataset.theme = initialTheme;
    document.documentElement.style.colorScheme = initialTheme;
    setTheme(initialTheme);
  }, []);

  useEffect(() => {
    async function loadSession() {
      try {
        const setup = await apiRequest<{
          requires_setup: boolean;
          setup_available: boolean;
          bootstrap_token_required: boolean;
          mfa_required: boolean;
        }>("/api/auth/setup-state");
        setSetupAvailable(setup.setup_available);
        setBootstrapTokenRequired(setup.bootstrap_token_required);
        setMfaRequired(setup.mfa_required);
        if (setup.requires_setup) {
          setGate("setup");
          return;
        }
        const currentUser = await apiRequest<User>("/api/auth/me");
        setUser(currentUser);
        setGate("authenticated");
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          setGate("login");
          return;
        }
        setGate("unavailable");
      }
    }
    void loadSession();
  }, []);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    setMessageKind("error");
    try {
      const payload = {
        email,
        password,
        ...(totpCode ? { totp_code: totpCode } : {}),
      };
      if (gate === "setup") {
        await apiRequest<User>("/api/auth/setup", {
          method: "POST",
          body: JSON.stringify({
            ...payload,
            display_name: displayName,
            ...(bootstrapToken ? { bootstrap_token: bootstrapToken } : {}),
          }),
        });
        setGate("login");
        setPassword("");
        setBootstrapToken("");
        setTotpCode("");
        setMessageKind("success");
        setMessage("Conta criada. Entre com sua senha e o código do autenticador para continuar.");
        return;
      }
      const signedInUser = await apiRequest<User>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setUser(signedInUser);
      setGate("authenticated");
      setPassword("");
      setTotpCode("");
    } catch (error) {
      setTotpCode("");
      setMessage(error instanceof Error ? error.message : "Ocorreu um erro inesperado.");
    } finally {
      setBusy(false);
    }
  }

  async function handleLogout() {
    setBusy(true);
    try {
      await apiRequest<void>("/api/auth/logout", { method: "POST" });
      setUser(null);
      setGate("login");
      setPassword("");
      setTotpCode("");
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Não foi possível encerrar a sessão.");
    } finally {
      setBusy(false);
    }
  }

  function changeTheme(nextTheme: Theme) {
    setTheme(nextTheme);
    document.documentElement.dataset.theme = nextTheme;
    document.documentElement.style.colorScheme = nextTheme;
    window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
  }

  if (gate === "authenticated" && user) {
    return (
      <AssistantWorkspace
        displayName={user.display_name}
        onLogout={() => void handleLogout()}
        onThemeChange={changeTheme}
        theme={theme}
      />
    );
  }

  return (
    <main className="auth-page">
      <section className="auth-brand-lockup" aria-label="SophIA — sua assistente financeira">
        <span className="assistant-brand-mark" aria-hidden="true">S</span>
        <span className="auth-brand-copy"><strong>SophIA</strong><small>sua assistente financeira</small></span>
      </section>

      {gate === "loading" && <LoadingState />}
      {gate === "unavailable" && <UnavailableState onRetry={() => window.location.reload()} />}
      {(gate === "setup" || gate === "login") && (
        gate === "setup" && !setupAvailable ? (
          <section className="auth-card">
            <div className="auth-heading">
              <p className="eyebrow">Primeiro acesso desativado</p>
              <h2>A conta ainda não foi habilitada.</h2>
              <p>O proprietário precisa configurar o token temporário de primeiro acesso no servidor.</p>
            </div>
          </section>
        ) : (
          <div className="auth-card">
            <div className="auth-heading">
              <p className="eyebrow">{gate === "setup" ? "Primeiro acesso" : "Bem-vindo de volta"}</p>
              <h2>{gate === "setup" ? "Crie sua conta" : "Entre na sua conta"}</h2>
              <p>
                {gate === "setup"
                  ? "Sua conta é privada e será usada para proteger seus dados."
                  : "Acesse seu espaço financeiro pessoal."}
              </p>
            </div>
            <form className="auth-form" onSubmit={handleSubmit}>
              {gate === "setup" && (
                <label className="field-label">
                  Como podemos chamar você?
                  <input
                    autoComplete="name"
                    required
                    maxLength={100}
                    value={displayName}
                    onChange={(event) => setDisplayName(event.target.value)}
                    placeholder="Seu nome"
                  />
                </label>
              )}
              {gate === "setup" && bootstrapTokenRequired && (
                <label className="field-label">
                  Token temporário de primeiro acesso
                  <input
                    autoComplete="off"
                    required
                    maxLength={256}
                    type="password"
                    value={bootstrapToken}
                    onChange={(event) => setBootstrapToken(event.target.value)}
                    placeholder="Token configurado no servidor"
                  />
                </label>
              )}
              <label className="field-label">
                E-mail
                <input
                  autoComplete="email"
                  required
                  maxLength={320}
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="voce@exemplo.com"
                />
              </label>
              <label className="field-label">
                Senha
                <input
                  autoComplete={gate === "setup" ? "new-password" : "current-password"}
                  required
                  minLength={12}
                  maxLength={128}
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Pelo menos 12 caracteres"
                />
              </label>
              {mfaRequired && (
                <label className="field-label">
                  Código do autenticador
                  <input
                    autoComplete="one-time-code"
                    inputMode="numeric"
                    maxLength={6}
                    minLength={6}
                    pattern="[0-9]{6}"
                    required
                    value={totpCode}
                    onChange={(event) => setTotpCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
                    placeholder="000000"
                  />
                </label>
              )}
              {message && (
                <p
                  className={`form-message ${messageKind === "success" ? "success-message" : ""}`}
                  role={messageKind === "success" ? "status" : "alert"}
                >
                  {message}
                </p>
              )}
              <button className="primary-button" type="submit" disabled={busy}>
                {busy ? "Aguarde…" : gate === "setup" ? "Criar conta privada" : "Entrar"}
                <span aria-hidden="true">↗</span>
              </button>
            </form>
            <p className="security-caption">
              <span aria-hidden="true">⌑</span>
              {mfaRequired
                ? "Sua sessão usa senha, código temporário e cookie seguro."
                : "Sua senha é protegida e nunca aparece em texto nos registros."}
            </p>
          </div>
        )
      )}
      <footer className="auth-page-footer">SophIA <span>·</span> Acesso privado</footer>
    </main>
  );
}

function LoadingState() {
  return (
    <div className="loading-state" role="status">
      <span className="loading-mark">S</span>
      <p>Preparando seu espaço…</p>
    </div>
  );
}

function UnavailableState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="auth-card unavailable-card">
      <p className="eyebrow">Conexão indisponível</p>
      <h2>Não conseguimos acessar o ambiente.</h2>
      <p>Confira se os serviços estão ativos e tente novamente.</p>
      <button type="button" className="primary-button" onClick={onRetry}>Tentar novamente <span aria-hidden="true">↻</span></button>
    </div>
  );
}
