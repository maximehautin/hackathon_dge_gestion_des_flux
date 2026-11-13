<script setup lang="ts">
defineProps<{
  siteName: string;
  heroTitle?: string;
  heroSubtitle?: string;
}>();
</script>
<template>
  <header>
    <div class="header-inner">
      <div
        class="republic"
        aria-label="République française, représentation indicative"
      >
        <div class="flag" aria-hidden="true"><i></i><i></i><i></i></div>
        RÉPUBLIQUE<br />FRANÇAISE
        <div class="motto">Liberté<br />Égalité<br />Fraternité</div>
      </div>
      <div class="site-mark" aria-hidden="true">
        <svg width="40" height="30" viewBox="0 0 40 30">
          <path d="M3 26 17 6 30 26Z" fill="currentColor" />
          <path d="m22 26 8-13 8 13" fill="#dfd9ff" />
        </svg>
      </div>
      <div class="brand">
        <strong>antaudiro</strong>
        <div>Anticiper les flux touristiques</div>
      </div>
      <nav class="nav">
        <NuxtLink to="/" class="nav-page">Tableau de bord</NuxtLink
        ><NuxtLink to="/modele" class="nav-page">Performance du modèle</NuxtLink>
      </nav>
    </div>
  </header>
  <section class="hero">
    <div class="hero-inner">
      <div class="eyebrow">Gestion des sites · Isère</div>
      <h1 id="siteTitle">{{ heroTitle ?? `Prévision d’affluence — ${siteName}` }}</h1>
      <p>{{ heroSubtitle ?? "Une vue simple pour préparer les prochains jours." }}</p>
    </div>
  </section>
</template>
<style scoped>
.nav-page {
  margin-left: 8px;
  padding-left: 24px;
  border-left: 1px solid var(--border-default);
  color: var(--blue-france);
  text-decoration: none;
  font-weight: 500;
}
.nav-page:hover {
  text-decoration: underline;
}
</style>
