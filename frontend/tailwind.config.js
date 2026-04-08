/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        uiuc: {
          orange: "#E84A27",
          blue: "#13294B",
        },
      },
    },
  },
  plugins: [],
};
