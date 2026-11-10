<script setup lang="ts">
import { hourlyValues } from "~/utils/forecast";

const props = defineProps<{
  peak: number;
  total: number;
  reference: number;
  threshold: number;
  date: string;
}>();

type ChartPoint = [number, number];

const max = computed(
  () =>
    Math.ceil(
      Math.max(50, props.peak * 1.2, props.threshold * 1.15) / 10,
    ) * 10,
);
const x = (hour: number) => 48 + ((hour - 8) / 12) * 385;
const y = (value: number) => 303 - (value / max.value) * 235;
const values = computed(() => hourlyValues(props.peak, props.total));
const referenceRatio = computed(() =>
  props.total ? props.reference / props.total : 0,
);
const points = computed<ChartPoint[]>(() =>
  values.value.map((value, index) => [x(8 + index + 0.5), y(value)]),
);
const referencePoints = computed<ChartPoint[]>(() =>
  values.value.map((value, index) => [
    x(8 + index + 0.5),
    y(value * referenceRatio.value),
  ]),
);
const path = (chartPoints: ChartPoint[]) =>
  chartPoints
    .map(
      ([pointX, pointY], index) =>
        `${index ? "L" : "M"}${pointX.toFixed(1)},${pointY.toFixed(1)}`,
    )
    .join(" ");
const forecastPath = computed(() => path(points.value));
const referencePath = computed(() => path(referencePoints.value));
const washPath = computed(() => {
  const first = points.value[0];
  const last = points.value[points.value.length - 1];
  if (!first || !last) return "";
  return `${forecastPath.value} L${last[0]},303 L${first[0]},303Z`;
});
const grid = computed(() =>
  Array.from({ length: 5 }, (_, index) => {
    const value = (max.value * index) / 4;
    return { value: Math.round(value), y: y(value) };
  }),
);
const hourGuides = computed(() =>
  Array.from({ length: 7 }, (_, index) => {
    const hour = 8 + index * 2;
    return { hour, x: x(hour) };
  }),
);
const peakX = x(14.5);
const peakY = computed(() => y(props.peak));
</script>

<template>
  <section class="chart-card">
    <h2>À quelle heure prévoir le plus de passages ?</h2>
    <div class="chart-caption">Passages entrants par heure · {{ date }}</div>
    <svg
      id="dailyChart"
      viewBox="0 0 460 370"
      role="img"
      :aria-label="`Courbe horaire de prévision pour le ${date}`"
    >
      <defs>
        <linearGradient id="wash" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#790bd0" stop-opacity=".12" />
          <stop offset="1" stop-color="#790bd0" stop-opacity="0" />
        </linearGradient>
      </defs>
      <text x="48" y="34" font-size="11" fill="#777">Passages / heure</text>
      <g v-for="line in grid" :key="line.value">
        <line
          x1="48"
          :y1="line.y"
          x2="433"
          :y2="line.y"
          stroke="#efefef"
        />
        <text
          x="38"
          :y="line.y + 4"
          text-anchor="end"
          font-size="11"
          fill="#666"
        >{{ line.value }}</text>
      </g>
      <g v-for="guide in hourGuides" :key="guide.hour">
        <line
          :x1="guide.x"
          y1="68"
          :x2="guide.x"
          y2="303"
          stroke="#f3f3f3"
        />
        <text
          :x="guide.x"
          y="328"
          text-anchor="middle"
          font-size="11"
          fill="#777"
        >{{ guide.hour }} h</text>
      </g>
      <path :d="washPath" fill="url(#wash)" />
      <path
        :d="referencePath"
        fill="none"
        stroke="#b5b5b5"
        stroke-dasharray="5 5"
        stroke-width="2"
      />
      <line
        x1="48"
        x2="433"
        :y1="y(threshold)"
        :y2="y(threshold)"
        stroke="#bc9400"
        stroke-dasharray="2 4"
      />
      <text
        x="431"
        :y="y(threshold) - 7"
        text-anchor="end"
        font-size="10"
        fill="#8b7319"
      >Vigilance · {{ threshold }} / h</text>
      <path
        :d="forecastPath"
        fill="none"
        stroke="#790bd0"
        stroke-width="4.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
      <circle
        :cx="peakX"
        :cy="peakY"
        r="8"
        fill="#ffcf00"
        stroke="white"
        stroke-width="2"
      />
      <rect
        :x="peakX - 42"
        :y="peakY - 42"
        rx="4"
        width="84"
        height="25"
        fill="#252525"
      />
      <text
        :x="peakX"
        :y="peakY - 26"
        text-anchor="middle"
        fill="white"
        font-size="10"
      >Pic · {{ peak }} / h</text>
    </svg>
    <div class="legend">
      <span><i class="swatch"></i>Prévision</span
      ><span><i class="swatch dashed"></i>Référence habituelle</span
      ><span><i class="swatch threshold"></i>Seuil de vigilance</span>
    </div>
    <div class="note">La référence illustre la moyenne des mêmes jours de semaine. La courbe horaire est une répartition type — le modèle est journalier.</div>
  </section>
</template>
