# TODO

## À faire

1. **Agrandir la base de données** : ajouter de nouveaux mouvements et de nouveaux artistes via
   `config.json` (`movements`, `extra_artists`), puis relancer `python3 fetch_works.py`.
2. ~~Changer la direction artistique.~~ Fait : style « blueprint néo-brutaliste » (variables en tête de `style.css`).
3. **Ajouter des curseurs de filtre à l'accueil** : ~~choix de la période~~ (fait : frise chronologique) ; reste le choix du style (mouvement).
4. ~~Ajouter un bouton « Quitter » accessible au milieu d'une partie.~~ Fait : croix en haut à droite de l'écran de question.
5. ~~Indiquer la période de la frise de l'œuvre au moment de la réponse.~~ Fait : bloc « Période » dans la carte
   de notice (nom, dates, explication, lien Wikipédia), alimenté par `description` et `wikipedia_url` dans
   `config.json`.

## Plus tard

- **Exclusion d'œuvres** : boutons « Masquer » et « Trop niche » pour écarter une œuvre, avec un export
  `excluded_works.json`.
- **Meilleur score par mode** : l'afficher (il est déjà enregistré dans le `localStorage`, sans affichage).
- **Raccourcis clavier**.
- **Corrections de difficulté** via `difficulty_overrides.json`.
