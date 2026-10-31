# kikapeint

Quiz d'art statique (HTML/JS, sans backend) pour GitHub Pages : on devine l'artiste d'une œuvre
parmi quatre artistes proches (même mouvement, même époque).

Les données viennent de Wikidata, Wikimedia Commons (images libres) et Wikipédia en français.
**Aucune image n'est stockée dans le dépôt** : `works.json` contient l'URL de la miniature à 800 px
hébergée par Commons.

## Tester en local

```bash
python3 -m http.server 8000
```

Puis ouvrir <http://localhost:8000>. Un serveur est nécessaire : le navigateur refuse de charger
`data/works.json` depuis un fichier ouvert directement (`file://`).

## Fichiers

| Fichier | Rôle | Modifié par le script ? |
|---|---|---|
| `config.json` | Périmètre : mouvements, artistes supplémentaires, plafonds | non |
| `manual_works.json` | Œuvres ajoutées à la main | **jamais** |
| `difficulty_overrides.json` | Surcharges de difficulté par œuvre ou artiste | **jamais** |
| `oeuvres_celebres_300.csv` | Liste d'œuvres célèbres à importer (entrée de `import_list.py`) | non |
| `import_list.py` | Retrouve les œuvres du CSV sur Wikidata et produit `curated_works.json` | — |
| `curated_works.json` | Œuvres importées du CSV (généré, fusionné par `fetch_works.py`) | oui, par `import_list.py` |
| `fetch_works.py` | Génère les données | — |
| `index.html`, `style.css`, `quiz.js`, `logic.js`, `favorites.js` | Le quiz (interface, tirage des questions, coups de cœur) | non |
| `favorites.json` | Coups de cœur exportés (facultatif, à la racine) | non : il vient de l'export du site |
| `data/works.json` | Données du quiz (généré, ne pas éditer à la main) | oui, entièrement réécrit |

## Régénérer les données

```bash
pip install requests
python3 fetch_works.py
```

Le script interroge Wikidata, filtre les images sous licence libre, récupère les notices, vérifie
chaque image par une requête HEAD (pause de 0,3 s entre les requêtes, User-Agent identifiable), puis
fusionne `manual_works.json` et écrit `data/works.json`. Il affiche un récapitulatif par mouvement.
La vérification des liens rend l'exécution longue (quelques minutes) ; `--skip-link-check` la saute,
pour le débogage uniquement.

## Importer une liste d'œuvres (CSV)

`import_list.py` lit `oeuvres_celebres_300.csv` (colonnes `titre_fr, title_en, artiste, annee, type, periode, lieu`),
retrouve chaque œuvre sur Wikidata (titre français ou anglais, et artiste), et écrit `curated_works.json` :

```bash
python3 import_list.py          # produit curated_works.json
python3 fetch_works.py          # le fusionne dans data/works.json
```

- Une ligne est écartée sans question si la correspondance est ambiguë (plusieurs versions ou fontes,
  œuvre en série, titre homonyme chez le même artiste), si l'œuvre n'a pas d'image Commons sous licence
  libre, ou si l'image ne répond pas à une requête HEAD.
- `movement` vient de la colonne `periode`, tel quel : il rejoint un mouvement existant seulement s'il
  porte exactement le même nom.
- Ces œuvres échappent aux plafonds par mouvement et par artiste. Si une œuvre a déjà le même `id` dans
  `works.json`, celle déjà présente est conservée.
- La notoriété et la difficulté sont calculées comme pour les autres œuvres, puis `difficulty_overrides.json`.
- `manual_works.json` n'est jamais modifié par ce script.

## Ajouter un mouvement

1. Trouve l'identifiant Wikidata du mouvement (page Wikidata, ex. `Q166593` pour le fauvisme).
   Attention aux homonymes : vérifie le libellé et le type « mouvement artistique ».
2. Ajoute une entrée dans `movements` de `config.json` :
   ```json
   {"id": "Q166593", "name": "Fauvisme", "year_min": 1850, "year_max": 1950}
   ```
   `year_min` et `year_max` sont facultatifs (valeurs globales par défaut) ; ils servent par exemple à
   limiter le cubisme à ses débuts.
3. Régénère (`python3 fetch_works.py`) et vérifie le récapitulatif : sous 8 artistes, le quiz à
   quatre choix est fragile.

## Ajouter un artiste

Pour récupérer les œuvres d'un artiste que le mouvement ne ramène pas, ajoute-le dans
`extra_artists` de `config.json`. Le mouvement doit exister dans `movements` :

```json
"extra_artists": [
  {"id": "Q37693", "movement": "Post-impressionnisme"}
]
```

L'identifiant est celui de l'artiste dans Wikidata. Seules ses peintures et sculptures de la période
configurée avec une image libre sont retenues.

## Ajouter une œuvre à la main

Ajoute un objet dans `manual_works.json` (tableau JSON). Le script lit ce fichier sans jamais
l'écrire, et les œuvres manuelles ne sont pas soumises aux plafonds.

```json
[
  {
    "title": "Les Nymphéas",
    "artist": "Claude Monet",
    "year": 1906,
    "movement": "Impressionnisme",
    "image": "https://commons.wikimedia.org/wiki/File:Claude_Monet_-_Water_Lilies_-_1906.jpg",
    "notice": "Texte court en français.",
    "museum": "Art Institute of Chicago"
  }
]
```

- Obligatoires : `title`, `artist`, `year`, `movement`, `image`. Le mouvement est celui sous lequel
  l'œuvre sera regroupée dans le quiz.
- `image` accepte la page `File:` ou `Fichier:` de Commons, une URL `Special:FilePath/...` ou le nom
  du fichier. Les URL `upload.wikimedia.org` ne sont pas supportées.
- Facultatifs : `notice`, `artist_notice` (texte sur la vie de l'artiste), `museum`, `type` (`peinture` par défaut ou `sculpture`), `notice_type`
  (`work` par défaut ou `artist`), `wikipedia_url`, `artist_id` (identifiant Wikidata, pour que
  l'artiste soit reconnu comme le même qu'une œuvre automatique).
- Licence et crédit sont lus automatiquement sur Commons. Une licence non libre déclenche un
  avertissement, et une image injoignable fait écarter l'œuvre avec un message.

Puis régénère les données.

## Coups de cœur

Après chaque réponse, deux boutons en forme de cœur permettent d'enregistrer l'œuvre et/ou l'artiste,
avec une note personnelle facultative. La page « Mes coups de cœur » (lien discret sur l'accueil) les
présente dans une galerie de cadres : un clic sur un cadre affiche la note, le titre, l'artiste et
l'année, et permet de modifier la note ou de retirer le coup de cœur. Un artiste est représenté par
son œuvre la plus connue (`work_fame` le plus élevé).

Les coups de cœur sont gardés dans le `localStorage` du navigateur (clé `kikapeint:favorites:v1`),
identifiés par `id` pour les œuvres et `artist_id` pour les artistes. Si le stockage est indisponible
(navigation privée, par exemple), le jeu fonctionne et les coups de cœur ne durent que le temps de la
page.

**Les sauvegarder dans le dépôt (pour GitHub Pages)** : le site étant statique, le navigateur ne peut pas
écrire dans le dépôt. La procédure est manuelle :

1. Sur la page « Mes coups de cœur », clique sur **Exporter** : le navigateur télécharge `favorites.json`.
2. Place ce fichier **à la racine du dépôt** (à côté de `index.html`), en remplaçant l'ancien.
3. Commite et pousse :
   ```bash
   git add favorites.json
   git commit -m "Mise à jour des coups de cœur"
   git push
   ```

Au chargement, le site lit `favorites.json` s'il existe et le fusionne avec le `localStorage` :
- une entrée qui existe des deux côtés garde la version du `localStorage` (note comprise) ;
- une entrée seulement dans le fichier est ajoutée ;
- un coup de cœur retiré dans le navigateur ne revient pas depuis le fichier, jusqu'à ce qu'on le
  rajoute ou qu'on réexporte.

Format : `{"version": 1, "works": [{"id", "note", "added", "label"}], "artists": [...]}`. `label` n'est
là que pour la lecture humaine et est ignoré au chargement.

## Périodes artistiques

Chaque œuvre a un champ `period` (identifiant d'une période définie dans `config.json`, clé `periods` :
`id`, `name`, `start`, `end`, `end: null` = aujourd'hui). Les bornes servent **uniquement à dessiner une frise**
(périodes contiguës, sans chevauchement : le script vérifie la contiguïté) ; elles n'attribuent pas les œuvres.

Attribution, dans cet ordre :
1. la table `movement_periods` de `config.json` (mouvement → identifiant de période) ;
2. sinon (mouvement absent de la table, ou ambigu comme `Expressionnisme`), la période dont le **centre**
   est le plus proche de l'année de l'œuvre. Les sculptures suivent les mêmes règles.

Le champ est posé à chaque génération. Pour le recalculer après avoir modifié les périodes ou la table, sans
réseau et sans toucher aux autres champs de `data/works.json` :

```bash
python3 fetch_works.py --periods-only
```

Le script affiche aussi un tableau par période (œuvres, peintures/sculptures, artistes, répartition par niveau).
L'accueil affiche une frise de 12 cases (une par période, largeur proportionnelle à la durée, 6 % minimum) :
un clic active ou désactive une période (sélection multiple, aucune = toutes). Une période sans œuvre dans
`works.json` est grisée (« Bientôt ») et devient cliquable dès qu'une œuvre lui est rattachée. Seules les œuvres
des périodes choisies sont posées ; les distracteurs viennent d'abord de ces périodes, puis le repli habituel
s'applique. Un mode est grisé s'il y a moins de 10 œuvres éligibles (Mixte : 4 + 3 + 3). La sélection est
mémorisée dans le `localStorage` (clé `kikapeint:periods:v1`).

## Difficulté

Chaque œuvre reçoit un niveau `facile`, `moyen` ou `difficile`, calculé à chaque génération.

**Notoriété.** `work_fame` et `artist_fame` valent le nombre de sitelinks Wikidata de l'œuvre et de
l'artiste (le nombre de langues où l'entité a un article). Avec l'option `--pageviews`, on ajoute
`round(10 × log10(1 + vues mensuelles moyennes))`, calculé sur les 12 derniers mois complets de
l'article fr.wikipedia (une requête par article, plus lent). Sans article en français, la part « vues »
est nulle.

**Niveaux.**
- `facile` : toute œuvre de la liste importée (`curated_works.json`, `difficulty_source: "curated"`), ou
  dont l'artiste ET l'œuvre sont très connus, c'est-à-dire `artist_fame` et `work_fame` au moins
  égaux à `easy_min_artist_fame` et `easy_min_work_fame` dans `config.json` (88 et 8).
  Dans le quiz, les trois mauvaises réponses de ce niveau sont aussi des artistes très connus.
- Le reste est coupé en deux moitiés sur `(work_fame, artist_fame)` (l'artiste départage les égalités
  d'œuvre) : la plus notoire est `moyen`, l'autre `difficile`. Deux œuvres de même clé ont le même niveau.
- Pour rendre le facile plus ou moins large, ajuste les deux seuils puis régénère. Regarde le récapitulatif
  (« 20 artistes les plus notoires ») pour choisir : il faut au moins 10 artistes distincts en facile.

**Surcharges.** `difficulty_overrides.json` est lu après le calcul et jamais écrit par le script :

```json
{
  "works":   {"Q18879691": "facile"},
  "artists": {"Q37693": "moyen"}
}
```

- `works` : identifiants Wikidata d'œuvres (ou `manual-...` pour une œuvre manuelle) ;
  `artists` : identifiants Wikidata d'artistes, ce qui change toutes leurs œuvres.
- Niveaux autorisés : `facile`, `moyen`, `difficile`. Un autre mot fait échouer la génération.
- Une surcharge d'œuvre l'emporte sur celle de son artiste.
- Un identifiant qui ne correspond à aucune œuvre retenue déclenche un avertissement.
- Les œuvres touchées ont `difficulty_source: "override"`.
- Les œuvres manuelles n'ont pas d'entité Wikidata : `work_fame` vaut 0 (et `artist_fame` aussi sans
  `artist_id` Wikidata), donc elles tombent en `difficile` sauf surcharge.

```bash
python3 fetch_works.py --pageviews   # notoriété avec vues Wikipédia
```

## Format de `data/works.json`

| Champ | Contenu |
|---|---|
| `id` | identifiant Wikidata, ou `manual-...` |
| `title`, `artist`, `artist_id`, `year`, `movement`, `type`, `museum` | description de l'œuvre |
| `image` | `https://commons.wikimedia.org/wiki/Special:FilePath/<fichier>?width=800` |
| `image_page` | page du fichier sur Commons |
| `image_license`, `image_credit` | licence et auteur de l'image |
| `notice` | texte court en français tiré de Wikipédia |
| `period` | identifiant de la période artistique (voir « Périodes artistiques ») |
| `notice_type` | `work` (article de l'œuvre) ou `artist` (article de l'artiste, à défaut) |
| `artist_notice` | présentation de l'artiste (intro de son article fr), seulement quand `notice` parle de l'œuvre ; sinon `null` |
| `work_fame`, `artist_fame` | scores de notoriété (voir « Difficulté ») |
| `difficulty`, `difficulty_source` | `facile` / `moyen` / `difficile` ; `computed` ou `override` |
| `wikipedia_url` | article Wikipédia dont vient la notice |
| `source` | `wikidata` ou `manual` |
