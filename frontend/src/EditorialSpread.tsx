import { Icon } from "./Icon";
import type { View } from "./Portal";
import "./editorial-spread.css";

type EditorialPhoto = {
  src: string;
  alt: string;
};

type EditorialSpreadProps = {
  photos: { detail: EditorialPhoto; inset: EditorialPhoto };
};

type CabinetLinksProps = {
  sections: View[];
  onNavigate: (view: View) => void;
};

const destinations = {
  profile: "Профиль",
  documents: "Документы",
  applications: "Заявления",
  staff: "Рабочее место",
} as const;

const destinationOrder: (keyof typeof destinations)[] = ["applications", "staff", "documents", "profile"];

export function CabinetLinks({ sections, onNavigate }: CabinetLinksProps) {
  const orderedSections = destinationOrder.filter((view) => sections.includes(view));

  return (
    <nav className="cabinet-links" aria-label="Быстрые переходы">
      {orderedSections.map((view) => (
        <button className="cabinet-links__destination" key={view} type="button" onClick={() => onNavigate(view)}>
          <span>{destinations[view]}</span>
          <Icon name="arrow-right" />
        </button>
      ))}
    </nav>
  );
}

export function EditorialSpread({ photos }: EditorialSpreadProps) {
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
    </div>
  );
}
