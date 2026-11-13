# Benchmark STT (§3, §10)

Critère : transcrire un chunk de 3 s en **moins de 3 s** sur le laptop de démo.
Au-delà de 3 s avec `small`, passer à `base` (`--model base`). Si `base` dépasse aussi 3 s,
abandonner les partiels (`--no-partiels`).

Commande : `python demo/bench.py voix.wav` (5 répétitions après échauffement, int8, CPU).

## Laptop de démo

À remplir au jour 1, avec une vraie voix.

| Modèle | Médiane | Min | Max | Verdict |
|---|---|---|---|---|
| small | | | | |
| base | | | | |

## Référence : sandbox de développement (pas le laptop de démo)

Mesuré le 2026-11-10 sur un conteneur Linux x86_64 à 12 cœurs, avec une voix de synthèse
(espeak-ng). La qualité de transcription n'est pas représentative d'une vraie voix.

| Modèle | Médiane | Min | Max | Verdict |
|---|---|---|---|---|
| small | 2,60 s | 2,37 s | 2,87 s | OK, mais proche du seuil |
| base | 0,79 s | 0,71 s | 1,32 s | OK |
