export default defineNuxtConfig({
  compatibilityDate: "2026-11-10",
  css: ["~/assets/css/main.css"],
  app: {
    head: { htmlAttrs: { lang: "fr" }, title: "Prévision d’affluence — Isère" },
  },
  devtools: { enabled: false },
});
