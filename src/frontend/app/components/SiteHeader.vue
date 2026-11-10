<template>
  <header>
    <div class="header-inner">
      <div class="republic">
        <div class="flag" aria-hidden="true"><i /><i /><i /></div>
        RÉPUBLIQUE<br />FRANÇAISE
      </div>
      <div class="brand">
        <strong>Anticiper les flux touristiques</strong>
        <div>Un tableau de bord pour les gestionnaires de sites</div>
      </div>
    </div>
  </header>
  <section class="hero">
    <div class="hero-inner">
      <h1>Prévision d’affluence — {{ siteName }}</h1>
      <p>Une vue simple pour préparer les prochains jours.</p>
    </div>
  </section>
</template>
<script setup lang="ts">
defineProps<{ siteName: string }>();
</script>
