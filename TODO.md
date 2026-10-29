# TODO

## À faire

1. **Agrandir la base de données** : ajouter de nouveaux mouvements et de nouveaux artistes via
   `config.json` (`movements`, `extra_artists`), puis relancer `python3 fetch_works.py`.
2. **Changer la direction artistique** : le rendu actuel fait trop « généré par IA ».
3. **Ajouter des curseurs de filtre à l'accueil** : choix du style (mouvement) et choix de la période.
4. **Ajouter un bouton « Quitter »** accessible au milieu d'une partie.

## Plus tard

- **Exclusion d'œuvres** : boutons « Masquer » et « Trop niche » pour écarter une œuvre, avec un export
  `excluded_works.json`.
- **Meilleur score par mode** : l'afficher (il est déjà enregistré dans le `localStorage`, sans affichage).
- **Raccourcis clavier**.
- **Corrections de difficulté** via `difficulty_overrides.json`.
