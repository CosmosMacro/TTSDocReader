# Atelier audiobook

## Parcours

L'accueil `/` et `/audiobook` proposent un atelier de projets locaux : import,
préparation des chapitres, choix de voix et aperçu, génération et assemblage.
Les formats d'entrée sont EPUB sans DRM, PDF textuel, DOCX, TXT et Markdown.
Un PDF scanné nécessite une reconnaissance de texte préalable ; l'application
n'effectue pas d'OCR.

Les chapitres exclus restent disponibles sous une forme compacte. Valider et
verrouiller un chapitre protège son texte sans empêcher l'écoute ou la génération.
La validation du texte, la disponibilité de l'audio et son écoute sont des états
distincts. Changer le texte ou la voix peut rendre l'audio obsolète : celui-ci
reste consultable, mais doit être régénéré pour participer au nouvel export.

Les corrections automatiques et IA sont proposées avant application. L'original
reste disponible et un historique borné permet de revenir sur les changements.
Les paramètres LLM sont accessibles dans les réglages ; le nettoyage déterministe
ne nécessite aucun appel externe.

L'action **Adapter à l'oral** demande une adaptation fidèle pour écoute seule,
pas un résumé. Elle peut retirer les références bibliographiques identifiables,
appels de notes, renvois et habillages de figures/tableaux. Les noms utiles à
l'argumentation restent attribués, sans année bibliographique. Les parenthèses
explicatives, nombres et dates utiles sont conservés ; une légende ou un tableau
qui apporte une information unique est intégré à la narration. Les nuances,
conditionnels, négations et liens de causalité ou d'association doivent rester
intacts. Les citations directes restent exactes. Les notes explicatives fournies
gardent leur sens sans leur appel. Le modèle ne doit rien déduire d'un visuel
absent ni inventer de note manquante. La proposition reste soumise à revue avant
application. Cette adaptation dépend du modèle : aucune transformation
automatique ne garantit qu'il reconnaîtra chaque artefact éditorial.

Vérification manuelle conseillée sur un court extrait : confirmer qu'une citation
bibliographique seule disparaît, qu'une parenthèse explicative et un chiffre
utile restent, qu'une légende informative rejoint la narration et qu'un
conditionnel reste conditionnel. Les tests automatisés vérifient le routage et
le contrat du prompt avec transport simulé ; ils ne mesurent pas la qualité réelle
d'une réponse fournisseur. Les chapitres trop longs (HTTP 413) et les limitations
du fournisseur (HTTP 429) ne sont pas contournés : découper le chapitre ou
réessayer ultérieurement.

## Données et exécution

- Les projets sont enregistrés dans `OUTPUT_DIR/projects/<identifiant unique>`.
  Deux documents de même nom ne partagent pas leurs fichiers.
- Les écritures de projet sont atomiques et portent une révision. Une sauvegarde
  issue d'une autre version est refusée au lieu d'écraser le travail courant.
- Les tâches audio sont exécutées hors de la requête HTTP. Leur état est consulté
  périodiquement par l'interface et reste enregistré sur disque.
- L'arrêt demandé est coopératif, entre les chapitres : une requête de synthèse
  déjà envoyée peut terminer et être facturée par le fournisseur.
- La génération individuelle et la génération de la sélection utilisent les
  mêmes fichiers et les mêmes règles de réutilisation.
- Assembler le M4B ne déclenche pas de synthèse. Les chapitres sélectionnés doivent
  avoir des audios à jour. L'assemblage respecte leur ordre et leurs titres.

La première version est destinée à une application locale, avec **un seul
processus serveur**. Les verrous de concurrence sont internes à ce processus ;
ne pas lancer plusieurs workers Uvicorn sur le même répertoire de projets.

## Prérequis

La génération de l'atelier utilise Fish Audio et nécessite `FISH_API_KEY` ainsi
que l'accord explicite de l'utilisateur avant envoi du texte. Les identifiants
de voix doivent correspondre à de vraies voix du fournisseur. Un aperçu est
également un appel de synthèse et peut être facturé.

FFmpeg et FFprobe servent à vérifier et assembler l'audio. Ils doivent être
accessibles dans le PATH, ou par `FFMPEG_BIN` et `FFPROBE_BIN` quand configurés.
Les estimations de prix sont indicatives et reposent sur le barème local de
l'application ; elles ne constituent pas un devis du fournisseur.

L'ancien convertisseur local reste accessible à `/tts` et l'ancienne interface
de revue à `/audiobook/legacy` pour compatibilité. L'atelier conserve FastAPI et
du JavaScript sans framework ; ses fichiers sont séparés dans `app/static/`.

## Validation

Les tests de projets couvrent les sauvegardes, révisions, verrous et tâches audio
avec un fournisseur simulé. Les tests navigateur couvrent les parcours de
l'atelier. Les tests média utilisent de vrais fichiers MP3 et FFmpeg, sans appel
à Fish Audio ni au LLM. La qualité subjective d'une voix nécessite une écoute
d'un extrait produit avec le fournisseur choisi.
