"use client";

import { useEffect, useState } from "react";
import Image from "next/image";

import { ApiError, apiRequest } from "@/lib/api";
import type { AuthUser } from "@/lib/auth-types";
import { AssistantWorkspace } from "@/components/assistant-workspace";
import { BrandMark } from "@/components/brand-mark";

type Gate = "loading" | "setup" | "login" | "authenticated" | "unavailable";
type LoginStep = "credentials" | "mfa";
type Theme = "light" | "dark";

const THEME_STORAGE_KEY = "finance-ai-theme";

export function AppShell() {
  const [gate, setGate] = useState<Gate>("loading");
  const [loginStep, setLoginStep] = useState<LoginStep>("credentials");
  const [user, setUser] = useState<AuthUser | null>(null);
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
  const [mfaEnrolled, setMfaEnrolled] = useState(false);
  const [mfaEnrollmentAvailable, setMfaEnrollmentAvailable] = useState(false);
  const [mfaEnrollmentOpen, setMfaEnrollmentOpen] = useState(false);
  const [enrollmentToken, setEnrollmentToken] = useState("");
  const [enrollmentQr, setEnrollmentQr] = useState("");
  const [enrollmentManualKey, setEnrollmentManualKey] = useState("");
  const [enrollmentCode, setEnrollmentCode] = useState("");
  const [enrollmentExpiresAt, setEnrollmentExpiresAt] = useState("");
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
        const currentUser = await apiRequest<AuthUser>("/api/auth/me");
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
        await apiRequest<AuthUser>("/api/auth/setup", {
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
        setMessage("Conta criada. Entre com seu e-mail e senha; depois a SophIA pedirá o código MFA.");
        return;
      }
      if (gate === "login" && loginStep === "credentials") {
        const credentials = await apiRequest<{
          mfa_required: boolean;
          mfa_enrolled: boolean;
          mfa_enrollment_available: boolean;
        }>("/api/auth/login/check", {
          method: "POST",
          body: JSON.stringify({ email, password }),
        });
        setMfaRequired(credentials.mfa_required);
        setMfaEnrolled(credentials.mfa_enrolled);
        setMfaEnrollmentAvailable(credentials.mfa_enrollment_available);
        if (credentials.mfa_required) {
          setLoginStep("mfa");
          setMessageKind("success");
          setMessage(
            credentials.mfa_enrolled
              ? "Senha confirmada. O MFA é obrigatório para proteger suas finanças. Abra o Authy, escolha SophIA e informe o código atual."
              : credentials.mfa_enrollment_available
                ? "Senha confirmada. O MFA é obrigatório para proteger suas finanças. Configure o Authy pela opção abaixo e confirme o primeiro código."
                : "Senha confirmada. O MFA é obrigatório para proteger suas finanças. Informe o código do Authy; se ainda não pareou, o responsável pelo servidor precisa habilitar o primeiro cadastro."
          );
          return;
        }
      }
      const signedInUser = await apiRequest<AuthUser>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setUser(signedInUser);
      setGate("authenticated");
      setLoginStep("credentials");
      setPassword("");
      setTotpCode("");
      setEnrollmentToken("");
      setEnrollmentCode("");
      setEnrollmentQr("");
    } catch (error) {
      setTotpCode("");
      setMessage(error instanceof Error ? error.message : "Ocorreu um erro inesperado.");
    } finally {
      setBusy(false);
    }
  }

  async function startMfaEnrollment(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    setMessageKind("error");
    try {
      const enrollment = await apiRequest<{
        qr_code_data_url: string;
        manual_key: string;
        expires_at: string;
      }>("/api/auth/mfa/enrollment/start", {
        method: "POST",
        body: JSON.stringify({ email, password, enrollment_token: enrollmentToken }),
      });
      setEnrollmentQr(enrollment.qr_code_data_url);
      setEnrollmentManualKey(enrollment.manual_key);
      setEnrollmentExpiresAt(enrollment.expires_at);
      setMessageKind("success");
      setMessage("QR criado. Adicione a SophIA no Authy e confirme com o código exibido no aplicativo.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Não foi possível iniciar o pareamento.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmMfaEnrollment(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    setMessageKind("error");
    try {
      const enrolledUser = await apiRequest<AuthUser>("/api/auth/mfa/enrollment/confirm", {
        method: "POST",
        body: JSON.stringify({
          email,
          password,
          enrollment_token: enrollmentToken,
          totp_code: enrollmentCode,
        }),
      });
      setUser(enrolledUser);
      setGate("authenticated");
      setLoginStep("credentials");
      setPassword("");
      setTotpCode("");
      setEnrollmentCode("");
      setEnrollmentToken("");
      setEnrollmentQr("");
      setEnrollmentManualKey("");
      setEnrollmentExpiresAt("");
    } catch (error) {
      setEnrollmentCode("");
      setMessage(error instanceof Error ? error.message : "Não foi possível confirmar o MFA.");
    } finally {
      setBusy(false);
    }
  }

  function returnToCredentials() {
    setLoginStep("credentials");
    setMfaEnrollmentOpen(false);
    setEnrollmentToken("");
    setEnrollmentCode("");
    setEnrollmentQr("");
    setEnrollmentManualKey("");
    setEnrollmentExpiresAt("");
    setTotpCode("");
    setMessage("");
    setMessageKind("error");
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
        avatarUrl={user.avatar_url ?? null}
        displayName={user.display_name}
        email={user.email}
        mfaRequired={user.mfa_required}
        mfaEnrolled={user.mfa_enrolled}
        onAvatarUrlChange={(nextAvatarUrl) => setUser((current) => current ? { ...current, avatar_url: nextAvatarUrl } : current)}
        onDisplayNameChange={(nextDisplayName) => setUser((current) => current ? { ...current, display_name: nextDisplayName } : current)}
        onLogout={() => void handleLogout()}
        onThemeChange={changeTheme}
        theme={theme}
      />
    );
  }

  return (
    <main className="auth-page">
      <section className="auth-brand-lockup" aria-label="SophIA — sua assistente financeira">
        <BrandMark />
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
              <p className="eyebrow">
                {gate === "setup" ? "Primeiro acesso" : loginStep === "mfa" ? "Verificação de segurança" : "Bem-vindo de volta"}
              </p>
              <h2>
                {gate === "setup"
                  ? "Crie sua conta"
                  : loginStep === "mfa"
                    ? mfaEnrollmentOpen ? "Configure o Authy" : "Confirme que é você"
                    : "Entre na sua conta"}
              </h2>
              <p>
                {gate === "setup"
                  ? "Sua conta é privada e será usada para proteger seus dados."
                  : loginStep === "mfa"
                    ? mfaEnrollmentOpen
                      ? enrollmentQr
                        ? "Escaneie o QR com o Authy e confirme o pareamento com o código de seis dígitos."
                        : "Informe o código temporário do servidor para gerar o QR seguro do Authy."
                      : "Sua conta exige autenticação multifator (MFA) para proteger suas finanças. Informe o código temporário do Authy."
                    : "Informe seu e-mail e senha. Em seguida, você confirmará o acesso com o MFA obrigatório."}
              </p>
            </div>
            {gate === "login" && loginStep === "mfa" && mfaEnrollmentOpen ? (
              enrollmentQr ? (
                <form className="auth-form" onSubmit={confirmMfaEnrollment}>
                  <div className="mfa-enrollment-qr-panel">
                    <Image className="mfa-enrollment-qr" src={enrollmentQr} alt="QR code para adicionar a SophIA ao Authy" width={240} height={240} unoptimized />
                    <p>Authy → adicionar conta → escanear QR code. O QR expira às {new Date(enrollmentExpiresAt).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}.</p>
                    <details>
                      <summary>Não consegue escanear?</summary>
                      <p>Adicione uma conta manualmente no Authy e informe esta chave:</p>
                      <code>{enrollmentManualKey}</code>
                    </details>
                  </div>
                  <label className="field-label">
                    Código de seis dígitos do Authy
                    <input
                      autoComplete="one-time-code"
                      inputMode="numeric"
                      maxLength={6}
                      minLength={6}
                      pattern="[0-9]{6}"
                      required
                      value={enrollmentCode}
                      onChange={(event) => setEnrollmentCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
                      placeholder="000000"
                    />
                  </label>
                  {message && <p className={`form-message ${messageKind === "success" ? "success-message" : ""}`} role={messageKind === "success" ? "status" : "alert"}>{message}</p>}
                  <button className="primary-button" type="submit" disabled={busy}>
                    {busy ? "Aguarde…" : "Confirmar e entrar"}<span aria-hidden="true">↗</span>
                  </button>
                  <button className="text-button auth-back-button" type="button" onClick={() => setMfaEnrollmentOpen(false)}>Voltar ao código MFA</button>
                </form>
              ) : (
                <form className="auth-form" onSubmit={startMfaEnrollment}>
                  <label className="field-label">
                    Código temporário de pareamento
                    <input
                      autoComplete="off"
                      required
                      minLength={32}
                      maxLength={256}
                      type="password"
                      value={enrollmentToken}
                      onChange={(event) => setEnrollmentToken(event.target.value)}
                      placeholder="Gerado no servidor para este primeiro pareamento"
                    />
                  </label>
                  <p className="mfa-enrollment-note">Esse código temporário autoriza somente o primeiro pareamento do Authy. Ele não é o código de seis dígitos do MFA.</p>
                  {message && <p className={`form-message ${messageKind === "success" ? "success-message" : ""}`} role={messageKind === "success" ? "status" : "alert"}>{message}</p>}
                  <button className="primary-button" type="submit" disabled={busy}>
                    {busy ? "Gerando QR…" : "Gerar QR code"}<span aria-hidden="true">↗</span>
                  </button>
                  <button className="text-button auth-back-button" type="button" onClick={() => setMfaEnrollmentOpen(false)}>Voltar ao login</button>
                </form>
              )
            ) : (
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
              {!(gate === "login" && loginStep === "mfa") && <label className="field-label">
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
              </label>}
              {!(gate === "login" && loginStep === "mfa") && <label className="field-label">
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
              </label>}
              {mfaRequired && (gate === "setup" || loginStep === "mfa") && (
                <label className="field-label">
                  Código de seis dígitos do Authy
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
              {gate === "login" && loginStep === "mfa" && mfaEnrollmentAvailable && !mfaEnrolled && (
                <div className="mfa-enrollment-link-row">
                  <span>Primeiro acesso ao Authy?</span>
                  <button className="text-button" type="button" onClick={() => { setMfaEnrollmentOpen(true); setMessage(""); }}>
                    Configurar autenticador
                  </button>
                </div>
              )}
              {gate === "login" && loginStep === "mfa" && (
                <button className="text-button auth-back-button" type="button" onClick={returnToCredentials}>Voltar e corrigir e-mail ou senha</button>
              )}
              <button className="primary-button" type="submit" disabled={busy}>
                {busy ? "Aguarde…" : gate === "setup" ? "Criar conta privada" : loginStep === "credentials" ? "Continuar" : "Entrar com MFA"}
                <span aria-hidden="true">↗</span>
              </button>
            </form>
            )}
            <p className="security-caption">
              <span aria-hidden="true">⌑</span>
              {mfaRequired
                ? "O acesso exige senha, código de uso único e sessão segura."
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
      <BrandMark className="loading-mark" size={30} />
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
