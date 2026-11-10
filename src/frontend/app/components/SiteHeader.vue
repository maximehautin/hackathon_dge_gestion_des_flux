<script setup lang="ts">
defineProps<{ siteName: string }>();
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
        <strong>Anticiper les flux touristiques</strong>
        <div>Un tableau de bord pour les gestionnaires de sites</div>
      </div>
      <nav class="nav">
        <a href="#previsions">← Prévisions</a
        ><a href="#semaine">← Vue à 7 jours</a><a href="#sources">← Données</a>
      </nav>
    </div>
  </header>
  <section class="hero">
    <div class="hero-inner">
      <div class="eyebrow">Gestion des sites · Isère</div>
      <h1 id="siteTitle">Prévision d’affluence — {{ siteName }}</h1>
      <p>Une vue simple pour préparer les prochains jours.</p>
    </div>
  </section>
</template>
