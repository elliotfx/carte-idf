# Carte IDF FFBB

Carte interactive des clubs engagés dans les championnats régionaux 5x5 de la Ligue Île-de-France FFBB.

Source utilisée : <https://competitions.ffbb.com/ligues/idf>

## Périmètre

Le projet respecte le périmètre suivant :

- ligue : Île-de-France
- départements : 75, 77, 78, 91, 92, 93, 94, 95
- compétitions : championnats régionaux 5x5 affichés sur la page FFBB de la ligue IDF
- genres : féminin et masculin
- catégories : seniors et jeunes
- localisation : adresse officielle du club
- géocodage : Nominatim / OpenStreetMap si la fiche FFBB ne donne pas de coordonnées
- affichage : un point par club, avec ses engagements régionaux
- filtres : niveau, département, genre, catégorie, club, championnat, poule

Aucune donnée fictive n'est fournie dans `data/clubs-idf.json`. Le fichier est volontairement vide au départ. Il faut lancer le script ou le workflow GitHub Actions pour générer les données.

## Structure du projet

```text
carte-idf/
├── index.html
├── style.css
├── app.js
├── data/
│   ├── clubs-idf.json
│   └── geocode-cache.json
├── scripts/
│   └── build_data.py
├── .github/
│   └── workflows/
│       └── update-data.yml
├── requirements.txt
└── README.md
```

## Lancer le site en local

Dans le dossier du projet :

```bash
python -m http.server 8000
```

Puis ouvrir :

```text
http://localhost:8000
```

## Générer les données en local

Installer les dépendances :

```bash
pip install -r requirements.txt
```

Lancer le script :

```bash
python scripts/build_data.py
```

Le script met à jour :

```text
data/clubs-idf.json
data/geocode-cache.json
```

Le cache de géocodage évite de redemander plusieurs fois les mêmes coordonnées à OpenStreetMap.

## Publier sur GitHub Pages

Le dépôt prévu est :

```text
https://github.com/elliotfx/carte-idf
```

Étapes :

1. Dézipper le projet.
2. Mettre les fichiers à la racine du dépôt `carte-idf`.
3. Faire un commit puis push.
4. Aller dans `Settings` puis `Pages`.
5. Dans `Build and deployment`, choisir `Deploy from a branch`.
6. Choisir la branche `main`, dossier `/root`.
7. Valider.

L'URL finale devrait être :

```text
https://elliotfx.github.io/carte-idf/
```

## Mettre à jour les données automatiquement

Le fichier suivant est déjà inclus :

```text
.github/workflows/update-data.yml
```

Il permet deux modes :

- lancement manuel depuis l'onglet `Actions` avec `Run workflow`
- lancement automatique chaque lundi à 05h00 UTC

Le workflow :

1. installe Python
2. installe les dépendances
3. lance `python scripts/build_data.py`
4. commit les fichiers JSON mis à jour
5. pousse les changements sur GitHub

## Logique de récupération des données

Le script ne part pas d'IDs inventés.

Il suit cette logique :

1. lire la page publique de la Ligue IDF
2. identifier les championnats régionaux 5x5 féminins et masculins
3. parcourir les 8 comités franciliens
4. récupérer les fiches clubs publiques
5. lire les engagements d'équipes sur chaque fiche club
6. conserver uniquement les engagements correspondant aux championnats régionaux IDF
7. récupérer l'adresse officielle du club
8. géocoder l'adresse avec Nominatim/OpenStreetMap
9. générer `data/clubs-idf.json`

## Données affichées sur la carte

Chaque point représente un club.

La popup affiche :

- nom du club
- adresse officielle
- niveau principal
- engagements filtrés
- lien vers la fiche FFBB

Exemple de filtre utile :

```text
Championnat : Régionale masculine seniors - Division 3
Poule : Poule B
```

La carte affichera alors les clubs ayant une équipe engagée dans cette poule.

## Couleurs

- NM/NF : rouge
- PNM/PNF/RM1/RF1 : orange
- RM2/RF2/RM3/RF3 et divisions régionales jeunes : bleu
- départemental : gris
- non classé : noir

## Limites connues

- La fiabilité dépend de la structure publique du site FFBB.
- Le géocodage dépend des résultats OpenStreetMap/Nominatim.
- Les clubs sans adresse ou sans géocodage valide restent dans le JSON mais ne sont pas affichés sur la carte.
- Le site n'appelle pas la FFBB en direct depuis le navigateur. Les données sont pré-générées pour que GitHub Pages reste rapide et propre.
