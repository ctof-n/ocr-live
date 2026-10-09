# ocr-live

Prototype d’une appli de traduction OCR live : **capture une fenêtre macOS**, **lit le texte** (Apple Vision) et **superpose la traduction** dans le navigateur.

## Architecture

```
Fenêtre du jeu → Quartz JPEG → navigateur
                 ↘ Vision OCR (~2 fps) → traduction → overlay canvas
```

Deux modes de capture :

1. **Capture native** — le serveur Python liste les fenêtres, envoie ~10 images/s, OCR + traduction.
2. **Capture navigateur** — `getDisplayMedia()` : le sélecteur macOS, plus fiable sur les jeux Metal.

Source **Tunic (runes)** : les glyphes Trunic (12 segments) sont lus comme des phonèmes anglais, puis traduits. Mets le jeu en fenêtré, texte bien contrasté.

L’OCR ne tourne que si l’image a changé (~2 fois par seconde). Les textes déjà vus restent en cache.

## Lancer

```bash
cd /Users/christophe/projects/ocr-live
source .venv/bin/activate
uvicorn server.main:app --host 127.0.0.1 --port 8787
```

Ouvre [http://127.0.0.1:8787](http://127.0.0.1:8787).

La permission **Enregistrement de l’écran** doit être donnée à l’app qui lance Python (Cursor ou Terminal). Mets le jeu en **fenêtré**.
