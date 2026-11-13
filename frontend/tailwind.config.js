/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        dm: ['"DM Sans"', "system-ui", "sans-serif"],
        inter: ["Inter", "system-ui", "sans-serif"],
      },
      colors: {
        // Taalmel palette: clinical calm rather than supplement freshness.
        ink: "#0C1110",
        bone: "#ECEDEC",
        paper: "#FEFDF9",
      },
    },
  },
  plugins: [],
};
