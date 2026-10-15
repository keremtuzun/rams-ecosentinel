"use client";
import { useEffect, useRef, useState } from "react";
const STEPS = [
  {
    target: "regions",
    title: "Bir bölge seç",
    text: "Hazır sonucu aç veya “Yeni analiz yap” ile kendi alanını ve tarihlerini seç.",
  },
  {
    target: "map",
    title: "Değişimi haritada gör",
    text: "Turuncu alanlar incelenmesi gereken yerler. Kesin orman kaybı anlamına gelmez.",
  },
  {
    target: "comparison",
    title: "Önce ve sonrayı karşılaştır",
    text: "Çubuğu sağa sola kaydır. Aynı yerin iki farklı tarihteki hâlini gör.",
  },
  {
    target: "exports",
    title: "Raporu indir",
    text: "PDF ile sonucu paylaş. Daha fazlası için “Ayrıntılar”ı aç.",
  },
];
export const TOUR_KEY = "ecosentinel-guide-tr-v1";
export default function Walkthrough({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState(0);
  const [rect, setRect] = useState<{
    left: number;
    top: number;
    width: number;
    height: number;
  } | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  const data = STEPS[step];
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const background = document.getElementById("app-shell");
    if (background) background.inert = true;
    return () => {
      if (background) background.inert = false;
      previous?.focus({ preventScroll: true });
    };
  }, []);
  useEffect(() => {
    const target =
      document.querySelector(`[data-guide="${data.target}"]`) ||
      document.querySelector('[data-guide="map"]');
    target?.scrollIntoView({ block: "center", behavior: "instant" });
    const update = () => {
      const b = target?.getBoundingClientRect();
      if (b)
        setRect({
          left: Math.max(8, b.left - 6),
          top: Math.max(8, b.top - 6),
          width: Math.min(b.width + 12, window.innerWidth - 16),
          height: Math.max(
            0,
            Math.min(b.bottom + 6, window.innerHeight - 8) -
              Math.max(8, b.top - 6),
          ),
        });
    };
    const frame = requestAnimationFrame(update);
    panel.current?.focus({ preventScroll: true });
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update);
    };
  }, [data.target]);
  function close() {
    try {
      localStorage.setItem(TOUR_KEY, "done");
    } catch {}
    onClose();
  }
  return (
    <div
      className="tour"
      onKeyDown={(e) => {
        if (e.key === "Escape") close();
        if (e.key === "Tab") {
          const buttons = panel.current?.querySelectorAll<HTMLButtonElement>(
            "button:not(:disabled)",
          );
          if (!buttons?.length) return;
          const first = buttons[0],
            last = buttons[buttons.length - 1];
          if (
            e.shiftKey &&
            (document.activeElement === first ||
              document.activeElement === panel.current)
          ) {
            e.preventDefault();
            last.focus();
          } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }}
    >
      {rect ? (
        <div className="tour-spotlight" style={rect} />
      ) : (
        <div className="tour-shade" />
      )}
      <div
        className="tour-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        aria-describedby="tour-description"
        tabIndex={-1}
        ref={panel}
      >
        <div className="tour-top">
          <span>
            Kısa tur · {step + 1} / {STEPS.length}
          </span>
          <button onClick={close} aria-label="Rehberi kapat">
            ×
          </button>
        </div>
        <div className="tour-progress" aria-hidden="true">
          {STEPS.map((_, i) => (
            <span key={i} className={i <= step ? "filled" : ""} />
          ))}
        </div>
        <h2 id="tour-title">{data.title}</h2>
        <p id="tour-description">{data.text}</p>
        <div className="tour-actions">
          <button className="quiet" onClick={close}>
            Atla
          </button>
          {step > 0 && (
            <button className="quiet" onClick={() => setStep(step - 1)}>
              Geri
            </button>
          )}
          <button
            className="primary"
            onClick={() =>
              step === STEPS.length - 1 ? close() : setStep(step + 1)
            }
          >
            {step === STEPS.length - 1 ? "Başlayalım" : "İleri →"}
          </button>
        </div>
      </div>
    </div>
  );
}
