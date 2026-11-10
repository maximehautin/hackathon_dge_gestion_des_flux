<script setup lang="ts">
import { hourlyValues } from "~/utils/forecast";
const props = defineProps<{
  peak: number;
  total: number;
  reference: number;
  threshold: number;
  date: string;
}>();
const max = computed(
  () =>
    Math.ceil(Math.max(50, props.peak * 1.2, props.threshold * 1.2) / 10) * 10,
);
const x = (index: number) => 48 + (index / 11) * 385;
const y = (value: number) => 303 - (value / max.value) * 235;
const values = computed(() => hourlyValues(props.peak, props.total));
const path = (reference = false) =>
  values.value
    .map(
      (v, i) =>
        `${i ? "L" : "M"}${x(i)},${y(v * (reference ? props.reference / props.total : 1))}`,
    )
    .join(" ");
</script>
<template>
  <section class="chart-card">
    <h2>À quelle heure prévoir le plus de passages ?</h2>
    <p class="small muted">Passages entrants par heure · {{ date }}</p>
    <svg
      viewBox="0 0 460 350"
      role="img"
      :aria-label="`Prévision horaire illustrative du ${date}`"
    >
      <g v-for="i in [0, 1, 2, 3, 4]" :key="i">
        <line
          x1="48"
          x2="433"
          :y1="y((max * i) / 4)"
          :y2="y((max * i) / 4)"
          stroke="#eee"
        />
        <text x="37" :y="y((max * i) / 4) + 4" text-anchor="end">
          {{ Math.round((max * i) / 4) }}
        </text>
      </g>
      <text
        v-for="(hour, i) in [8, 10, 12, 14, 16, 18]"
        :key="hour"
        :x="x(i * 2)"
        y="328"
        text-anchor="middle"
      >
        {{ hour }} h
      </text>
      <line
        x1="48"
        x2="433"
        :y1="y(threshold)"
        :y2="y(threshold)"
        stroke="#ba9400"
        stroke-dasharray="2 4"
      />
      <path
        :d="path(true)"
        fill="none"
        stroke="#aaa"
        stroke-width="2"
        stroke-dasharray="5 5"
      />
      <path
        :d="path()"
        fill="none"
        stroke="#790bd0"
        stroke-width="4.5"
        stroke-linejoin="round"
        stroke-linecap="round"
      />
      <circle
        :cx="x(6)"
        :cy="y(peak)"
        r="8"
        fill="#ffcf00"
        stroke="white"
        stroke-width="2"
      />
      <rect
        :x="x(6) - 40"
        :y="y(peak) - 40"
        width="80"
        height="25"
        rx="4"
        fill="#252525"
      />
      <text :x="x(6)" :y="y(peak) - 24" fill="white" text-anchor="middle">
        Pic · {{ peak }} / h
      </text>
    </svg>
    <div class="legend">
      <span>🟣 Prévision</span><span>┄ Référence habituelle</span
      ><span>⋯ Seuil de vigilance</span>
    </div>
  </section>
</template>
