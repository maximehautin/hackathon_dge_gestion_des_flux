<script setup lang="ts">
import { validThresholds, type Thresholds } from "~/utils/forecast";
const model = defineModel<Thresholds>({ required: true });
const moderate = ref(model.value.moderate);
const high = ref(model.value.high);
const valid = computed(() =>
  validThresholds(Number(moderate.value), Number(high.value)),
);
const scale = ref(100);
watch([moderate, high], () => {
  if (!valid.value) return;
  scale.value = Math.max(
    scale.value,
    Math.ceil(Number(high.value) / 100) * 100,
  );
  model.value = { moderate: Number(moderate.value), high: Number(high.value) };
});
</script>
<template>
  <section class="threshold-panel">
    <div class="section-heading">
      <div>
        <h2>Vos seuils de vigilance</h2>
        <p class="muted small">
          Choisissez à partir de combien de passages par heure le niveau change.
        </p>
      </div>
      <span class="unit-tag">Passages / heure</span>
    </div>
    <div class="threshold-editors">
      <div
        v-for="key in ['moderate', 'high'] as const"
        :key="key"
        class="threshold-editor"
      >
        <label :for="key"
          ><i class="dot" :class="key" />Vigilance
          {{ key === "moderate" ? "modérée" : "élevée" }}</label
        >
        <div class="threshold-input">
          <span>À partir de</span
          ><input
            :id="key"
            :value="key === 'moderate' ? moderate : high"
            type="number"
            min="1"
            max="10000"
            :aria-invalid="!valid"
            @input="
              key === 'moderate'
                ? (moderate = Number(($event.target as HTMLInputElement).value))
                : (high = Number(($event.target as HTMLInputElement).value))
            "
          /><span>passages / h</span>
        </div>
        <input
          :aria-label="key === 'moderate' ? 'Seuil modéré' : 'Seuil élevé'"
          type="range"
          min="1"
          :max="scale"
          :value="key === 'moderate' ? moderate : high"
          @input="
            key === 'moderate'
              ? (moderate = Number(($event.target as HTMLInputElement).value))
              : (high = Number(($event.target as HTMLInputElement).value))
          "
        />
      </div>
    </div>
    <div class="threshold-preview" aria-live="polite">
      <div class="low">
        <strong>Faible</strong><span>Moins de {{ model.moderate }}</span>
      </div>
      <div class="moderate">
        <strong>Modérée</strong
        ><span>{{ model.moderate }} à {{ model.high - 1 }}</span>
      </div>
      <div class="high">
        <strong>Élevée</strong><span>{{ model.high }} et plus</span>
      </div>
    </div>
    <p v-if="!valid" role="alert" class="error small">
      Le seuil élevé doit être supérieur au seuil modéré (entiers de 1 à 10
      000). Les dernières valeurs valides restent appliquées.
    </p>
    <div class="threshold-bottom">
      <span class="muted small"
        >Seuils de passages horaires, sans mesure de l’occupation.</span
      ><span class="small">{{
        valid ? "● Application automatique" : "Valeurs à corriger"
      }}</span>
    </div>
  </section>
</template>
