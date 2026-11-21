import { Icon } from "./Icon";
import type { View } from "./Portal";
import "./editorial-spread.css";

type EditorialPhoto = {
  src: string;
  alt: string;
};

type EditorialSpreadProps = {
  photos: { detail: EditorialPhoto; inset: EditorialPhoto };
  sections: { view: View; description: string }[];
  firstName?: string | null;
  staff: boolean;
  onNavigate: (view: View) => void;
};

const destinations = {
  profile: "Профиль",
  documents: "Документы",
  applications: "Заявления",
  staff: "Рабочее место",
} as const;

const destinationOrder: (keyof typeof destinations)[] = ["profile", "documents", "applications", "staff"];

export function EditorialSpread({ photos, sections, firstName, staff, onNavigate }: EditorialSpreadProps) {
  const orderedSections = destinationOrder.flatMap((view) => {
    const section = sections.find((entry) => entry.view === view);
    return section ? [{ ...section, title: destinations[view] }] : [];
  });

  return (
    <div className="editorial-spread">
      <section className="spread-gallery" aria-label="Галерея самолёта">
        <figure className="spread-detail">
          <img src={photos.detail.src} alt={photos.detail.alt} loading="lazy" />
        </figure>
        <div className="spread-gallery-aside">
          <figure className="spread-thumbnail">
            <img src={photos.inset.src} alt={photos.inset.alt} loading="lazy" />
          </figure>
          <div className="spread-gallery-notes">
            <div>
              <h2>Ту-144ЛЛ</h2>
              <p>Летающая лаборатория на базе сверхзвукового пассажирского самолёта.</p>
            </div>
            <div>
              <h2>Приёмная комиссия</h2>
              <p>Сроки, правила и направления подготовки.</p>
              <a href="https://priem.mai.ru/" target="_blank" rel="noreferrer">
                Сайт комиссии <Icon name="external" />
              </a>
            </div>
          </div>
        </div>
      </section>
      <section className="spread-guide" aria-labelledby="home-sections">
        <div className="spread-guide-heading">
          <h2 id="home-sections">{staff ? "Работа с заявлениями" : "Как поступить"}</h2>
          {firstName && <p>Здравствуйте, {firstName}</p>}
        </div>
        <div className="spread-destinations">
          {orderedSections.map(({ view, title, description }) => (
            <button
              type="button"
              key={view}
              className={view === "applications" || view === "staff" ? "spread-destination spread-destination--primary" : "spread-destination"}
              onClick={() => onNavigate(view)}
            >
              <strong>{title}</strong>
              <span>{description}</span>
              <Icon name="arrow-right" />
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
