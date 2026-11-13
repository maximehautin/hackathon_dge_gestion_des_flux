<script setup lang="ts">
import { formatDate, levelLabels, type Level } from "~/utils/forecast";
defineProps<{
  cards: Array<{
    date: string;
    today: boolean;
    past: boolean;
    forecast: { total: number } | null;
    historical: number | null;
    level: Level | null;
    holiday?: string;
    vacation?: string;
  }>;
  selected: string;
  connected: boolean;
}>();
const emit = defineEmits<{ select: [date: string] }>();
</script>
<template>
  <section class="week-section" id="semaine">
    <div class="section-heading">
      <h2>Votre semaine en un regard</h2>
      <span>Choisissez une journée</span>
    </div>
    <div class="week-grid">
      <button
        v-for="day in cards"
        :key="day.date"
        class="day-card"
        :class="{
          selected: selected === day.date,
          unavailable: !day.forecast && day.historical === null,
          observed: day.historical !== null && !day.forecast,
        }"
        :disabled="!day.forecast && day.historical === null"
        :aria-pressed="selected === day.date"
        :aria-label="
          formatDate(day.date, {
            weekday: 'long',
            day: 'numeric',
            month: 'long',
          })
        "
        @click="emit('select', day.date)"
      >
        <span class="day-date"
          ><span>{{ formatDate(day.date, { weekday: "short" }) }}</span
          ><strong>{{ Number(day.date.slice(-2)) }}</strong></span
        >
        <span class="today-marker">{{ day.today ? "Aujourd'hui" : " " }}</span>
        <strong class="day-total">{{
          day.forecast?.total ?? (day.historical !== null ? day.historical : "—")
        }}</strong
        ><span class="small muted">{{
          day.forecast ? "passages" : day.historical !== null ? "observés" : "Non disponible"
        }}</span>
        <span v-if="day.level" class="badge" :class="day.level">{{
          day.historical !== null && !day.forecast ? "Observé" : levelLabels[day.level]
        }}</span
        ><span v-else class="small muted">{{
          !connected ? "Non connecté" : day.past ? "Passé" : "Hors prévision"
        }}</span>
        <span class="calendar-labels"
          ><span v-if="day.holiday" class="calendar-badge" :title="day.holiday"
            >Férié</span
          ><span
            v-if="day.vacation"
            class="calendar-badge vacation"
            :title="day.vacation"
            >Vacances · A</span
          ></span
        >
      </button>
    </div>
  </section>
</template>
