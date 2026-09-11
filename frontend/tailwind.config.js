/** @type {import('tailwindcss').Config} */
// Design tokens mirror the Strancer / Stitch dark theme (Material Design 3 anchors):
// periwinkle primary, teal secondary, deep-navy surfaces.
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        background: "#051424",
        "on-background": "#d4e4fa",
        surface: "#051424",
        "surface-bright": "#2c3a4c",
        "surface-container": "#122131",
        "surface-container-high": "#1c2b3c",
        "surface-container-highest": "#273647",
        "surface-container-low": "#0d1c2d",
        "surface-container-lowest": "#010f1f",
        "surface-variant": "#273647",
        "on-surface": "#d4e4fa",
        "on-surface-variant": "#c7c4d7",
        primary: "#c0c1ff",
        "on-primary": "#1000a9",
        "primary-container": "#8083ff",
        "on-primary-container": "#0d0096",
        secondary: "#4fdbc8",
        "on-secondary": "#003731",
        "secondary-container": "#04b4a2",
        tertiary: "#bec6e0",
        error: "#ffb4ab",
        "on-error": "#690005",
        "error-container": "#93000a",
        outline: "#908fa0",
        "outline-variant": "#464554",
      },
      borderRadius: {
        DEFAULT: "0.25rem",
        lg: "0.5rem",
        xl: "0.75rem",
        full: "9999px",
      },
      spacing: {
        gutter: "24px",
        "margin-page": "40px",
        "sidebar-width": "280px",
        "container-max": "1440px",
      },
      fontFamily: {
        "display-lg": ["Outfit", "sans-serif"],
        "headline-md": ["Outfit", "sans-serif"],
        "body-lg": ["Inter", "sans-serif"],
        "body-md": ["Inter", "sans-serif"],
        "code-sm": ["Geist", "monospace"],
        "label-caps": ["Geist", "sans-serif"],
      },
    },
  },
  plugins: [],
};
