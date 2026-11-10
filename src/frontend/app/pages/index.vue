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
  today,
} = useDashboard();
const longDate = (date: string) =>
  formatDate(date, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
</script>
<template>
  <SiteHeader :site-name="site.name" />
  <main>
    <div class="context">
      <div class="site-picker">
        <label for="site">Site touristique</label
        ><select id="site" v-model="siteId">
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
    <template v-if="selected?.forecast && selected.level">
      <div class="selected-day-heading">
        <span>Détail de la journée</span
        ><strong>{{ longDate(selected.date) }}</strong>
      </div>
      <section class="summary-grid">
        <div class="metric">
          <span class="muted small">Vigilance prévisionnelle</span>
          <div class="value">{{ levelLabels[selected.level] }}</div>
          <span class="small"
            ><i class="dot" :class="selected.level" />{{
              selected.level === "low"
                ? "Pas de dépassement prévu"
                : "À surveiller autour de 14 h"
            }}</span
          >
        </div>
        <div class="metric">
          <span class="muted small">Passages prévus sur la journée</span>
          <div class="value">
            {{ selected.forecast.total }} <small>passages</small>
          </div>
          <span class="muted small"
            >À l’accès Tuilerie · passages entrants</span
          >
        </div>
        <div class="metric">
          <span class="muted small">Météo de la journée</span>
          <div class="value weather">
            {{ selected.forecast.rain === 0 ? "☀ Temps sec" : "☂ Pluie" }}
          </div>
          <span class="muted small"
            >{{ selected.forecast.rain.toLocaleString("fr-FR") }} mm de
            précipitations · Neige : 0 cm</span
          >
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
    <section v-else class="empty">
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
      <button
        class="today-button"
        @click="
          siteId = 'herretang';
          today();
        "
      >
        Revenir à l’Herretang · aujourd’hui
      </button>
    </section>
    <ThresholdSettings v-model="thresholds" />
    <details class="sources">
      <summary>Sources, fiabilité et limites</summary>
      <p>
        Cette interface utilise des données de démonstration. Le modèle Python
        existant produit actuellement des prévisions journalières ; la courbe
        horaire est illustrative et n’est pas déduite de ses résultats.
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
    <footer>
      Prévisions et météo : données de démonstration · Hackathon DGE · Équipe 2
    </footer>
  </main>
</template>
