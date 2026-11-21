import type { CSSProperties } from "react";

const glyphs = {
  "home": 0xe0f5,
  "chat": 0xe116,
  "file": 0xe0cc,
  "folder": 0xe33f,
  "user": 0xe468,
  "staff": 0xe5d5,
  "arrow-right": 0xe049,
  "plus": 0xe13d,
  "arrow-up": 0xe04a,
  "paperclip": 0xe12d,
  "check": 0xe06c,
  "clock": 0xe087,
  "book": 0xe05f,
  "grid": 0xe0ff,
  "external": 0xe04d,
  "telegram": 0xe152,
  "logout": 0xe10e,
  "menu": 0xe115,
  "x": 0xe1b2,
  "refresh": 0xe145,
  "chevron-right": 0xe06f,
  "chevron-down": 0xe06d,
  "search": 0xe151,
  "info": 0xe0f9,
  "inbox": 0xe0f7,
  "upload": 0xe19e,
  "spark": 0xe412,
  "eye": 0xe0ba,
  "eye-off": 0xe0bb,
  "link": 0xe103,
  "more": 0xe0b6,
  "orbit": 0xe3e7,
  "mail": 0xe10f,
  "shield": 0xe1ff,
  "graduation": 0xe234,
  "copy": 0xe09e,
  "badge": 0xe241,
  "alert": 0xe077,
  "panel-left": 0xe12a,
  "plane": 0xe1de,
};

export type IconName = keyof typeof glyphs;

export function Icon({ name, className, style }: { name: IconName; className?: string; style?: CSSProperties }) {
  return <span aria-hidden="true" className={className ? `ui-icon ${className}` : "ui-icon"} style={style}>{String.fromCodePoint(glyphs[name])}</span>;
}
