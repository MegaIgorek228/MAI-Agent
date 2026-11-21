import type { CSSProperties } from "react";

import type { User } from "./api";
import { AircraftScene } from "./AircraftScene";
import type { AircraftFocus } from "./AircraftViewer";
import { Icon } from "./Icon";
import type { IconName } from "./Icon";
import type { View } from "./Portal";
import "./aircraft-map.css";

type Location = {
  view: "documents" | "profile" | "agent";
  label: string;
  description: string;
  icon: IconName;
  x: number;
  focus: Exclude<AircraftFocus, "overview">;
};

const locations: Location[] = [
  { view: "documents", label: "Кабина пилотов", description: "Документы и статус поступления", icon: "file", x: 17, focus: "cockpit" },
  { view: "profile", label: "Моё место", description: "Личные данные", icon: "user", x: 33, focus: "seat" },
  { view: "agent", label: "Салон", description: "Диалог с ассистентом", icon: "chat", x: 62, focus: "lounge" },
];

type AircraftMapProps = { user: User; view: View; onNavigate: (view: View) => void };

export function AircraftMap({ user, view, onNavigate }: AircraftMapProps) {
  const destinations = locations.filter((location) => location.view !== "documents" || user.role !== "student");
  const selected = destinations.find((location) => location.view === view)
    ?? (view === "applications" || view === "staff" ? destinations.find((location) => location.view === "documents") : undefined);
  const overview = view === "home";
  const focusX = selected?.x ?? 50;
  const camera = {
    "--camera-inset": `${50 - focusX}%`,
    "--camera-point": `${focusX}%`,
    "--camera-zoom": overview ? 1 : 2.85,
  } as CSSProperties;

  return (
    <section className="flight-map" data-view={view} aria-label="Карта самолёта">
      <header className="flight-map__heading">
        {overview ? (
          <>
            <h1>На борту</h1>
            <p><span className="flight-map__rotate-hint">Поверните самолёт перетаскиванием. </span>Выберите зону, чтобы открыть раздел.</p>
          </>
        ) : (
          <>
            <button type="button" className="flight-map__back" onClick={() => onNavigate("home")}>
              <Icon name="arrow-right" /> Весь самолёт
            </button>
            {selected && <p className="flight-map__current"><Icon name={selected.icon} /> {selected.label}</p>}
          </>
        )}
      </header>
      <div className="flight-map__scene">
        <AircraftScene focus={selected?.focus ?? "overview"} onSelect={(focus) => {
          const destination = destinations.find((location) => location.focus === focus);
          if (destination) onNavigate(destination.view);
        }} fallback={<>
          <div className="flight-map__viewport">
            <div className="flight-map__model" style={camera}>
              <img src="/cabin-cutaway.webp" alt="Самолёт в разрезе с кабиной пилотов, креслами пассажиров и салоном" />
            </div>
          </div>
          {overview && (
            <div className="flight-map__hotspots" aria-label="Зоны на изображении">
              {destinations.map((location) => (
                <button key={location.view} className="flight-map__marker" type="button"
                  style={{ "--marker-x": `${location.x}%` } as CSSProperties}
                  onClick={() => onNavigate(location.view)}>
                  <Icon name={location.icon} />
                  <span>{location.label}</span>
                </button>
              ))}
            </div>
          )}
        </>} />
      </div>
      <nav className="flight-map__routes" aria-label="Зоны самолёта">
        {destinations.map((location) => (
          <button key={location.view} type="button" className="flight-map__route" onClick={() => onNavigate(location.view)}
            aria-current={selected?.view === location.view ? "location" : undefined}>
            <span className="flight-map__route-icon"><Icon name={location.icon} /></span>
            <span className="flight-map__route-text">
              <strong>{location.label}</strong>
              <small>{location.description}</small>
            </span>
            <Icon name="arrow-right" className="flight-map__route-arrow" />
          </button>
        ))}
      </nav>
    </section>
  );
}
