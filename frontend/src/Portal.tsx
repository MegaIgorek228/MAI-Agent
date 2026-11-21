import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";

import type { DocumentItem, Profile, User } from "./api";
import { EditorialSpread } from "./EditorialSpread";
import { Icon } from "./Icon";

export type View = "home" | "profile" | "documents" | "applications" | "staff" | "agent";
export type AuthMode = "login" | "register";

const viewTitles: Record<View, string> = {
  home: "Главная",
  agent: "Ассистент",
  applications: "Заявления",
  documents: "Документы",
  staff: "Рабочее место",
  profile: "Профиль"
};

const roles: Record<string, string> = {
  applicant: "Абитуриент",
  student: "Студент",
  admissions_staff: "Сотрудник приёмной комиссии",
  administrator: "Администратор"
};

const admissionsUrl = "https://priem.mai.ru/";

export function isStaff(user: User) {
  return user.role === "admissions_staff" || user.role === "administrator";
}

const aircraft = {
  hero: {
    src: "/tu-144-cutout.webp",
    alt: "Сверхзвуковой самолёт Ту-144ЛЛ в полёте"
  },
  detail: {
    src: "/mai-aircraft-detail.webp",
    alt: "Сопла двигателей Ту-144 крупным планом"
  },
  inset: {
    src: "/mai-aircraft-inset.webp",
    alt: "Ту-144ЛЛ на взлёте в Жуковском"
  }
};

function Brand() {
  return (
    <span className="brand">
      <span className="brand__words">
        <strong><span>MAI</span> Agent</strong>
        <small>Приёмная комиссия</small>
      </span>
    </span>
  );
}

function AircraftPhoto({ className, action }: { className: string; action?: ReactNode }) {
  return (
    <figure className={className}>
      <div className="aircraft-frame">
        <img src={aircraft.hero.src} alt={aircraft.hero.alt} fetchPriority="high" />
        {action}
      </div>
    </figure>
  );
}

type AuthScreenProps = {
  mode: AuthMode;
  email: string;
  password: string;
  error: string;
  pending: boolean;
  onEmailChange: (email: string) => void;
  onPasswordChange: (password: string) => void;
  onModeChange: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

export function AuthScreen({
  mode, email, password, error, pending, onEmailChange, onPasswordChange, onModeChange, onSubmit
}: AuthScreenProps) {
  const [passwordVisible, setPasswordVisible] = useState(false);
  const signingIn = mode === "login";

  return (
    <div className="auth-page">
      <header className="auth-masthead">
        <Brand />
        <a href={admissionsUrl} target="_blank" rel="noreferrer" className="topbar-link">
          Сайт приёмной комиссии <Icon name="external" />
        </a>
      </header>
      <main className="auth-shell">
        <div className="auth-publication">
          <p className="auth-publication__title">Поступление <br /><span>в МАИ</span></p>
          <AircraftPhoto className="auth-visual" />
        </div>
        <section className="auth-side" aria-labelledby="auth-title">
          <div className="auth-main">
            <div className="auth-heading">
              <h1 id="auth-title">{signingIn ? "Вход в кабинет" : "Регистрация"}</h1>
              <p>{signingIn ? "Введите email и пароль, чтобы войти." : "Создайте аккаунт для работы с документами и заявлениями."}</p>
            </div>
            <form onSubmit={onSubmit} className="auth-form">
              <label className="auth-field">
                Email
                <span className="auth-input">
                  <Icon name="mail" />
                  <input name="email" type="email" autoComplete="username" value={email}
                    placeholder="name@example.com" onChange={(event) => onEmailChange(event.target.value)} required />
                </span>
              </label>
              <div className="auth-field">
                <label htmlFor="auth-password">Пароль</label>
                <div className="auth-input">
                  <Icon name="shield" />
                  <input id="auth-password" name="password" type={passwordVisible ? "text" : "password"} minLength={8}
                    autoComplete={signingIn ? "current-password" : "new-password"} value={password}
                    placeholder={signingIn ? "Введите пароль" : "Не менее 8 символов"}
                    onChange={(event) => onPasswordChange(event.target.value)} required />
                  <button type="button" className="auth-reveal button-icon"
                    aria-label={passwordVisible ? "Скрыть пароль" : "Показать пароль"}
                    onClick={() => setPasswordVisible((visible) => !visible)}>
                    <Icon name={passwordVisible ? "eye-off" : "eye"} />
                  </button>
                </div>
              </div>
              {error && <p className="error" role="alert">{error}</p>}
              <button className="auth-submit" type="submit" disabled={pending}>
                {pending ? (signingIn ? "Входим…" : "Создаём аккаунт…") : (signingIn ? "Войти" : "Создать аккаунт")}
                {!pending && <Icon name="arrow-right" />}
              </button>
            </form>
            <div className="auth-switch">
              <span>{signingIn ? "Впервые здесь?" : "Уже есть аккаунт?"}</span>
              <button type="button" className="button-link" disabled={pending} onClick={() => {
                setPasswordVisible(false);
                onModeChange();
              }}>
                {signingIn ? "Зарегистрироваться" : "Войти в кабинет"}
              </button>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

function identity(user: User, profile: Profile | null) {
  const name = [profile?.first_name, profile?.last_name].filter(Boolean).join(" ");
  const initials = name
    ? name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("")
    : user.email.slice(0, 2);

  return { name: name || user.email, initials: initials.toUpperCase(), role: roles[user.role] ?? user.role };
}

type WorkspaceProps = {
  user: User;
  profile: Profile | null;
  view: View;
  error: string;
  onNavigate: (view: View) => void;
  onLogout: () => void;
  children: ReactNode;
};

export function Workspace({ user, profile, view, error, onNavigate, onLogout, children }: WorkspaceProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuToggle = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!menuOpen) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
        menuToggle.current?.focus();
      }
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [menuOpen]);

  const account = identity(user, profile);
  const nav: View[] = ["home", "agent"];
  if (user.role === "applicant") nav.push("applications");
  if (user.role !== "student") nav.push("documents");
  if (isStaff(user)) nav.push("staff");
  nav.push("profile");

  const navigate = (next: View) => {
    setMenuOpen(false);
    onNavigate(next);
  };

  return (
    <div className={view === "home" ? "app-shell app-shell--home" : "app-shell"}>
      <header className="app-header">
        <div className="app-masthead">
          <button type="button" className="brand-button" onClick={() => navigate("home")}><Brand /></button>
          <button ref={menuToggle} type="button" className="app-menu-toggle"
            onClick={() => setMenuOpen((open) => !open)}
            aria-label={menuOpen ? "Закрыть меню" : "Открыть меню"}
            aria-expanded={menuOpen} aria-controls="app-sidebar">
            <Icon name={menuOpen ? "x" : "menu"} />
            <span>Меню</span>
          </button>
          <div id="app-sidebar" className={menuOpen ? "app-sidebar app-sidebar--open" : "app-sidebar"}>
            <nav className="app-nav" aria-label="Разделы кабинета">
              {nav.map((item) => (
                <button className="nav-item" type="button" key={item} onClick={() => navigate(item)}
                  aria-current={view === item ? "page" : undefined}>
                  <span>{viewTitles[item]}</span>
                </button>
              ))}
            </nav>
            <div className="masthead-account">
              <button className="masthead-account__profile" type="button" onClick={() => navigate("profile")}
                aria-label="Открыть учётную запись" title={account.name}>
                <span className="avatar">{account.initials}</span>
                <span className="masthead-account__text">
                  <strong>{account.name}</strong>
                  <small>{account.role}</small>
                </span>
              </button>
              <button type="button" className="masthead-account__logout" onClick={onLogout} title="Выйти">
                <Icon name="logout" /><span>Выйти</span>
              </button>
            </div>
          </div>
        </div>
      </header>
      {menuOpen && <button type="button" tabIndex={-1} aria-hidden="true" className="mobile-backdrop" onClick={() => setMenuOpen(false)} />}
      <div className="app-column">
        {view !== "home" && (
          <div className="app-topbar">
            <div className="breadcrumbs">
              <button type="button" className="button-link" onClick={() => navigate("home")}>Кабинет</button>
              <Icon name="chevron-right" />
              <span>{viewTitles[view]}</span>
            </div>
            <a href={admissionsUrl} target="_blank" rel="noreferrer" className="topbar-link">
              Сайт приёмной комиссии <Icon name="external" />
            </a>
          </div>
        )}
        <main className={view === "home" ? "app-content app-content--home" : "app-content"}>
          {error && <p className="error global-error" role="alert">{error}</p>}
          {children}
        </main>
      </div>
    </div>
  );
}

type HomePageProps = {
  user: User;
  profile: Profile | null;
  documents: DocumentItem[];
  pairingCode: string;
  pairingPending: boolean;
  onPair: () => void;
  onNavigate: (view: View) => void;
};

export function HomePage({ user, profile, documents, pairingCode, pairingPending, onPair, onNavigate }: HomePageProps) {
  const [copiedCode, setCopiedCode] = useState("");
  const sections: { view: View; description: string }[] = [];
  if (user.role === "applicant") {
    sections.push({ view: "applications", description: "Подача заявления и проверка статуса" });
  }
  if (isStaff(user)) {
    sections.push({ view: "staff", description: "Проверка заявлений и публикация правил" });
  }
  if (user.role !== "student") {
    sections.push({
      view: "documents",
      description: documents.length
        ? `Загружено файлов: ${documents.length}`
        : "Загрузка файлов и проверка комплектности"
    });
  }
  sections.push({ view: "profile", description: "Контакты и параметры поступления" });

  const firstName = profile?.first_name?.trim();

  return (
    <div className="home-page">
      <section className="home-lead" aria-labelledby="home-title">
        <p className="home-lead__summary">
          {isStaff(user) ? "Работа приёмной комиссии" : "Личный кабинет абитуриента"}
        </p>
        <h1 id="home-title">
          {isStaff(user) ? "Приёмная кампания" : <>Поступление <span className="home-lead__place">в МАИ</span></>}
        </h1>
      </section>
      <AircraftPhoto className="editorial-photo" action={
        <button className="editorial-action" type="button" onClick={() => onNavigate("agent")}>
          Спросить ассистента <Icon name="arrow-right" />
        </button>
      } />
      <EditorialSpread sections={sections} firstName={firstName} staff={isStaff(user)} photos={aircraft} onNavigate={onNavigate} />
      <section className="telegram-panel" aria-labelledby="telegram-title">
        <div className="telegram-panel__icon"><Icon name="telegram" /></div>
        <div className="telegram-panel__text">
          <h2 id="telegram-title">MAI Agent в Telegram</h2>
          <p>Привяжите кабинет, чтобы общаться с ассистентом в Telegram.</p>
          {pairingCode && (
            <div className="pair-command">
              <span>Отправьте боту <code>/pair {pairingCode}</code>. Код действует 10 минут.</span>
              <button type="button" className="button-secondary" onClick={async () => {
                try {
                  await navigator.clipboard.writeText(`/pair ${pairingCode}`);
                  setCopiedCode(pairingCode);
                } catch {
                  setCopiedCode("");
                }
              }}><Icon name={copiedCode === pairingCode ? "check" : "copy"} />
                {copiedCode === pairingCode ? "Скопировано" : "Копировать"}
              </button>
            </div>
          )}
        </div>
        <button type="button" className="button-secondary telegram-panel__action" onClick={onPair} disabled={pairingPending}>
          {pairingPending ? "Создаём код…" : "Привязать Telegram"}
        </button>
      </section>
    </div>
  );
}

type ProfilePageProps = {
  user: User;
  profile: Profile | null;
  pending: boolean;
  saved: boolean;
  onSave: (event: FormEvent<HTMLFormElement>) => void;
  onChange: () => void;
};

export function ProfilePage({ user, profile, pending, saved, onSave, onChange }: ProfilePageProps) {
  const account = identity(user, profile);

  return (
    <section className="profile-page" aria-labelledby="profile-title">
      <header className="page-heading">
        <h1 id="profile-title">Профиль</h1>
        <p>Укажите контактные данные и параметры поступления.</p>
      </header>
      <div className="profile-layout">
        {profile ? (
          <form className="profile-editor" onSubmit={onSave} onChange={onChange}>
            <section className="surface-panel profile-section">
              <h2>Личные данные</h2>
              <div className="profile-fields">
                <label>Имя<input name="first_name" autoComplete="given-name" defaultValue={profile.first_name ?? ""} /></label>
                <label>Фамилия<input name="last_name" autoComplete="family-name" defaultValue={profile.last_name ?? ""} /></label>
                <label>Телефон<input name="phone" type="tel" autoComplete="tel" defaultValue={profile.phone ?? ""} /></label>
              </div>
            </section>
            <section className="surface-panel profile-section">
              <h2>Поступление</h2>
              <div className="profile-fields">
                <label>Направление подготовки<input name="target_program" defaultValue={profile.target_program ?? ""} /></label>
                <label>Основание поступления<input name="admission_basis" defaultValue={profile.admission_basis ?? ""} /></label>
              </div>
            </section>
            <div className="profile-actions">
              <button type="submit" disabled={pending}>{pending ? "Сохраняем…" : "Сохранить профиль"}</button>
              {saved && <p className="save-status" role="status"><Icon name="check" /> Профиль сохранён.</p>}
            </div>
          </form>
        ) : <p className="muted">Данные профиля недоступны.</p>}
        <aside className="surface-panel profile-summary">
          <span className="avatar avatar--large">{account.initials}</span>
          <h2>Учётная запись</h2>
          <p>{user.email}</p>
          <span className="role-badge">{account.role}</span>
        </aside>
      </div>
    </section>
  );
}
