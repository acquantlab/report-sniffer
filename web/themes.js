// Colour themes: the interface (CSS variables), the sniffer, the marks on the page and the exported reports
// (analyst/themes.py holds the same accents). The choice is remembered in this browser.

import { COLORS } from "./sniffer.js";

// a dark terminal screen; each theme changes the phosphor colour and the selection colour
const dark = (o) => ({
  "--bg": "#000000", "--panel": "#07090c", "--bar": "#12161b", "--line": "#2a3038", "--faint": "#181c22",
  "--text": "#ece9df", "--text2": "#c4c1b6", "--muted": "#878c96", "--wait": "#4a4f58",
  "--accent": "#ff9f1a", "--accent-ink": "#000000", "--accent-soft": "#2b1c05", "--input": "#ffd34d",
  "--sel": "#0a2f6b", "--sel-ink": "#ffffff", "--link": "#5aa2ff",
  "--up": "#2fd27a", "--down": "#ff5147", "--ok": "#2fd27a", "--veil": "rgba(0, 0, 0, .88)",
  "--warn-bg": "#2a0b09", "--warn-ink": "#ffc9c4", ...o,
});

export const THEMES = {
  terminal: {
    name: { en: "Terminal (amber)", it: "Terminale (ambra)" }, swatch: "#ff9f1a", dark: true,
    css: dark({}),
    sniffer: { back: "#000000", frame: "#ff9f1a", mark: "#f4f1e8" },
    ping: "#e07b00", sight: "#1f6fe0", marker: "#ffd34d",
  },
  phosphor: {
    name: { en: "Phosphor (green)", it: "Fosforo (verde)" }, swatch: "#35e07f", dark: true,
    css: dark({ "--accent": "#35e07f", "--accent-soft": "#062414", "--input": "#b6ffd0", "--sel": "#0b4a2a", "--link": "#7fe7ff",
                "--text": "#dff5e6", "--text2": "#b3d2bf", "--up": "#35e07f", "--ok": "#35e07f" }),
    sniffer: { back: "#000000", frame: "#35e07f", mark: "#eafff1" },
    ping: "#0f9d52", sight: "#0e8fa8", marker: "#b6ffd0",
  },
  desk: {
    name: { en: "Desk (blue)", it: "Desk (blu)" }, swatch: "#4aa3ff", dark: true,
    css: dark({ "--bg": "#050b14", "--panel": "#08111d", "--bar": "#0f1c2e", "--line": "#22344d", "--faint": "#12203a",
                "--accent": "#4aa3ff", "--accent-soft": "#0a2140", "--input": "#ffffff", "--sel": "#16407a", "--link": "#8cc4ff",
                "--text": "#e8eef7", "--text2": "#bccadd", "--muted": "#8192a8", "--veil": "rgba(5, 11, 20, .9)" }),
    sniffer: { back: "#050b14", frame: "#4aa3ff", mark: "#ffffff" },
    ping: "#1c6fd1", sight: "#d9730d", marker: "#ffd34d",
  },
  paper: {
    name: { en: "Paper (light)", it: "Carta (chiaro)" }, swatch: "#f3f1ea",
    css: {
      "--bg": "#f3f1ea", "--panel": "#fbfaf6", "--bar": "#e6e3d9", "--line": "#c9c5b8", "--faint": "#e9e6dc",
      "--text": "#14181f", "--text2": "#333a45", "--muted": "#666c76", "--wait": "#b3b0a6",
      "--accent": "#b85c00", "--accent-ink": "#ffffff", "--accent-soft": "#f6e3cc", "--input": "#14181f",
      "--sel": "#12305c", "--sel-ink": "#ffffff", "--link": "#12509e",
      "--up": "#0a7a45", "--down": "#b3261e", "--ok": "#0a7a45", "--veil": "rgba(243, 241, 234, .9)",
      "--warn-bg": "#fbe9e7", "--warn-ink": "#6b1a14",
    },
    sniffer: { back: "#14181f", frame: "#ffb454", mark: "#ffffff" },
    ping: "#b85c00", sight: "#12509e", marker: "#ffd34d",
  },
};

const DEFAULT = "terminal";
let current = DEFAULT;

export function themeId() { return current; }
export function theme() { return THEMES[current]; }

export function applyTheme(id) {
  current = THEMES[id] ? id : DEFAULT;
  const th = THEMES[current], root = document.documentElement;
  for (const [k, v] of Object.entries(th.css)) root.style.setProperty(k, v);
  root.dataset.theme = current;
  root.style.colorScheme = th.dark ? "dark" : "light";
  Object.assign(COLORS, th.sniffer, { ping: th.ping, sight: th.sight });
  try { localStorage.setItem("sniffer-theme", current); } catch { /* private window: not remembered */ }
  return th;
}

export function savedTheme() {
  try { return localStorage.getItem("sniffer-theme") || DEFAULT; } catch { return DEFAULT; }
}

// "rgba(r,g,b,a)" from "#rrggbb"
export function rgba(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}
