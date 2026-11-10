<script setup lang="ts">
import { formatDate, offsetDate, levelLabels } from "~/utils/forecast";
const {
  anchor,
  siteId,
  site,
  sites,
  week,
  lastWeek,
  cards,
  selectedDate,
  selected,
  thresholds,
  periodLabel,
  loading,
  error,
  today,
  trainStatus,
  trainSite,
} = useDashboard();
const longDate = (date: string) =>
  formatDate(date, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });

const isTraining = computed(() => trainStatus.value === "training");
const isTrainError = computed(() => trainStatus.value === "error");
function goToHerretang() {
  siteId.value = "herretang";
  today();
}
const trainLabel = computed(() => {
  if (trainStatus.value === "training") return "Entraînement en cours…";
  if (trainStatus.value === "done") return "Modèle prêt — rechargement…";
  return "Entraîner le modèle";
});
</script>
<template>
  <SiteHeader :site-name="site.name" />
  <div v-if="error" role="alert" class="api-error">
    {{ error }}
  </div>
  <main id="previsions">
    <div v-if="loading" class="loading" aria-live="polite">Chargement des prévisions…</div>
    <div class="context">
      <div class="site-picker">
        <label for="siteSelect">Site touristique</label
        ><select id="siteSelect" v-model="siteId">
          <option v-for="item in sites" :key="item.id" :value="item.id">
            {{ item.name }}
          </option>
        </select>
      </div>
      <nav class="week-controls" aria-label="Navigation par semaine">
        <button
          class="week-arrow"
          :disabled="week <= -52"
          aria-label="Semaine précédente"
          @click="week--"
        >
          ‹
        </button>
        <div class="week-caption">
          <span>Semaine du lundi au dimanche</span
          ><strong>{{ periodLabel }}</strong>
        </div>
        <button
          class="week-arrow"
          :disabled="week >= lastWeek"
          aria-label="Semaine suivante"
          @click="week++"
        >
          ›</button
        ><button v-if="week !== 0" class="today-button" @click="today">
          Revenir à aujourd’hui
        </button>
      </nav>
    </div>
    <WeekOverview
      :cards="cards"
      :selected="selectedDate"
      :connected="site.available"
      @select="selectedDate = $event"
    />
    <p class="horizon-note">
      Prévisions jusqu’au {{ formatDate(offsetDate(anchor, 6)) }} inclus · 7
      jours à compter d’aujourd’hui
    </p>
    <!-- Détail prévision (jours futurs) -->
    <template v-if="selected?.forecast && selected.level">
      <div class="selected-day-heading">
        <span>Détail de la journée</span
        ><strong>{{ longDate(selected.date) }}</strong>
      </div>
      <section class="summary-grid" aria-label="Synthèse de la journée">
        <div class="metric">
          <div class="label">Vigilance prévisionnelle</div>
          <div class="value">{{ levelLabels[selected.level] }}</div>
          <span class="status"
            ><i class="dot" :style="{ background: selected.level === 'high' ? '#ac4747' : selected.level === 'low' ? '#61785a' : '#b58300' }" />{{
              selected.level === "low"
                ? "Pas de dépassement prévu"
                : "À surveiller autour de 14 h"
            }}</span
          >
        </div>
        <div class="metric">
          <div class="label">Passages prévus sur la journée</div>
          <div class="value">
            {{ selected.forecast.total }} <small>passages</small>
          </div>
          <span class="sub">{{ site.name }} · passages entrants</span>
        </div>
        <div class="metric weather-metric">
          <div class="label">Météo de la journée</div>
          <div class="weather-main">
            <svg
              width="38"
              height="38"
              viewBox="0 0 40 40"
              fill="none"
              stroke="currentColor"
              stroke-width="1.7"
              stroke-linecap="round"
              aria-hidden="true"
            >
              <template v-if="selected.forecast.rain === 0">
                <circle cx="20" cy="20" r="7" />
                <path
                  d="M20 3v5m0 24v5M3 20h5m24 0h5M8 8l4 4m16 16 4 4M8 32l4-4M28 12l4-4"
                />
              </template>
              <template v-else>
                <path
                  d="M10 26a7 7 0 1 1 1-14 9 9 0 0 1 17 2 6 6 0 0 1 1 12H10Z"
                />
                <path d="m14 30-2 5m9-5-2 5m9-5-2 5" />
              </template>
            </svg>
            <div class="value">
              {{
                selected.forecast.rain === 0
                  ? "Temps sec"
                  : selected.forecast.rain < 1
                    ? "Pluie faible"
                    : "Pluie"
              }}
            </div>
          </div>
          <div class="sub">
            {{ selected.forecast.rain.toLocaleString("fr-FR") }} mm de
            précipitations · Neige : 0 cm
          </div>
        </div>
      </section>
      <HourlyChart
          :peak="selected.forecast.peak"
          :total="selected.forecast.total"
          :reference="selected.forecast.reference"
          :threshold="thresholds.moderate"
          :date="longDate(selected.date)"
        />
    </template>
    <ThresholdSettings v-model="thresholds" />

    <!-- Détail historique (jours passés avec données CSV) -->
    <template v-else-if="selected?.historical !== null && selected?.historical !== undefined && selected.level">
      <div class="selected-day-heading">
        <span>Données observées</span
        ><strong>{{ longDate(selected.date) }}</strong>
      </div>
      <section class="summary-grid">
        <div class="metric">
          <span class="muted small">Niveau de fréquentation</span>
          <div class="value">{{ levelLabels[selected.level] }}</div>
          <span class="small"><i class="dot" :class="selected.level" />Comptage réel · source CSV</span>
        </div>
        <div class="metric">
          <span class="muted small">Passages observés sur la journée</span>
          <div class="value">
            {{ selected.historical }} <small>passages</small>
          </div>
          <span class="muted small">{{ site.name }} · passages entrants</span>
        </div>
      </section>
    </template>

    <!-- Aucune donnée disponible pour la période -->
    <section v-else class="history-empty">
      <h2>
        {{
          site.available
            ? "Aucune donnée historique connectée"
            : "Prévisions non connectées"
        }}
      </h2>
      <p>
        {{
          site.available
            ? "Cette période est passée. Les comptages observés restent à connecter."
            : `Le site ${site.name} est sélectionné. Ses prévisions restent à connecter.`
        }}
      </p>
      <template v-if="!site.available && site.has_data">
        <button
          class="today-button"
          :disabled="isTraining"
          @click="trainSite"
        >
          {{ trainLabel }}
        </button>
        <p v-if="isTrainError" class="muted small" style="margin-top:.5rem">
          Erreur durant l’entraînement. Vérifiez les logs de l’API.
        </p>
      </template>
      <button v-else class="today-button" @click="goToHerretang">
        Revenir à l’Herretang · aujourd’hui
      </button>
    </section>
    <details class="trust" id="sources">
      <summary>Sources, fiabilité et limites de la prévision</summary>
      <p>
        Prévisions fournies par le modèle XGBoost de l’équipe 2. La courbe
        horaire est illustrative (répartition type) et non issue du modèle journalier.
      </p>
      <p>
        Les passages entrants à un accès ne représentent ni des visiteurs
        uniques, ni une occupation simultanée. Les autres sites et l’historique
        ne sont pas connectés.
      </p>
      <p>
        Calendriers : jours fériés métropolitains et vacances scolaires
        Grenoble, zone A (instantanés officiels 2025–2027 pour les vacances ; à
        actualiser). Aucun service de notification n’est connecté.
      </p>
    </details>
    <div class="footer-line">
      <span>Prévisions XGBoost · Météo Open-Meteo</span
      ><span>Hackathon DGE · Équipe 2</span>
    </div>
  </main>
</template>
