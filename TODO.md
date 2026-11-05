# TODO

## À faire

1. **Agrandir la base de données** : ajouter de nouveaux mouvements et de nouveaux artistes via
   `config.json` (`movements`, `extra_artists`), puis relancer `python3 fetch_works.py`.
2. **Ajouter des curseurs de filtre à l'accueil** : reste le choix du style (mouvement).

## Plus tard

- **Exclusion d'œuvres** : boutons « Masquer » et « Trop niche » pour écarter une œuvre, avec un export
  `excluded_works.json`.
- **Meilleur score par mode** : l'afficher (il est déjà enregistré dans le `localStorage`, sans affichage), plus une série de jours consécutifs.
- **Corrections de difficulté** via `difficulty_overrides.json`.

## Idées (à trier)

Expérience de jeu
- **Autres types de question** : « Dans quelle période ? », « Quelle année approximative ? » (curseur sur la frise).
- **Défi du jour** : mêmes 10 œuvres pour tout le monde, tirées avec la date comme graine (sans backend).
- **Zoom sur l'image** pendant la question.
- **Indice optionnel** (période ou année) qui réduit les points, pour les niveaux moyen et difficile.

Contenu
- **Plus d'œuvres faciles en Art contemporain et en Rococo** (Facile y est grisé) : via `difficulty_overrides.json`
  (ex. *Peines del Viento*, *Éloge de l'horizon*).
- **Dates des Chillida à vérifier** (*Elogio al Horizonte* 2005 ou 1990 ? *Homenaje a A. Fleming* 1955) ; retirer le
  doublon *L'Homme qui marche*.
- **Filtre par artiste**, en plus du style.

Fiche et apprentissage
- **Œuvres à revoir** : écran des œuvres les plus ratées.

Technique
- **Vérifier l'affichage mobile** de la fiche et de l'écran de fin.
- **Mode hors ligne** (PWA légère) et pré-chargement de l'image de la question suivante.
- **Accessibilité** : contraste, ordre du focus dans la fenêtre modale, annonces lecteur d'écran.
