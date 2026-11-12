# Newsletter Hebdo Bourse & Crypto → Discord

Bot 100 % gratuit hébergé sur **GitHub Actions** qui envoie chaque **lundi, mercredi et vendredi à 13h15 heure de San Francisco** (juste après la clôture du Nasdaq) une newsletter structurée sur **Discord** (avec notification push sur téléphone).

## Contenu de la newsletter
- **Notification push résumée** : S&P 500, Nasdaq, CAC 40, Bitcoin.
- **Indices clés** : clôture et performance hebdomadaire + journalière.
- **Géants de la Tech US** : Apple, Microsoft, NVIDIA, Alphabet, Amazon, Meta, Tesla, Broadcom.
- **CAC 40** : Top 3 hausses et Top 3 baisses de la semaine.
- **Crypto** : Bitcoin (BTC), Ethereum (ETH), Solana (SOL) sur 24h et 7j.
- **Actualités marquantes** : gros titres de la semaine (Google News RSS) + **résumé éditorial IA optionnel** via Gemini API Free Tier.

---

## Mise en place en 3 étapes (5 minutes, 100 % gratuit)

### 1. Créer un Webhook Discord (30 secondes)
1. Sur Discord, crée un serveur privé (ou utilise un salon privé dédié sur un de tes serveurs).
2. Va dans **Paramètres du salon** (icône engrenage) → **Intégrations** → **Webhooks** → **Nouveau webhook**.
3. Donne-lui un nom (ex. `Market Brief`) et clique sur **Copier l'URL du webhook**.
4. Active les notifications mobiles sur ce salon Discord si besoin.

### 2. Pousser le code sur GitHub et ajouter le secret
1. Crée un nouveau dépôt sur GitHub (privé ou public, les deux sont gratuits — un dépôt privé a 2 000 min/mois sur GitHub Free et ce bot consomme ~1 min/mois).
2. Pousse ce dossier sur ton dépôt GitHub :
   ```bash
   git init
   git add .
   git commit -m "Initial weekly market Discord newsletter"
   git branch -M main
   git remote add origin https://github.com/<TON_USER>/<TON_REPO>.git
   git push -u origin main
   ```
3. Sur GitHub, va dans **Settings** → **Secrets and variables** → **Actions** → **New repository secret** :
   - Name : `DISCORD_WEBHOOK_URL`
   - Secret : colle l'URL du webhook Discord.
4. *(Optionnel — gratuit)* Si tu veux un court paragraphe de synthèse rédigé par IA au-dessus des chiffres, ajoute un second secret `GEMINI_API_KEY` avec une clé gratuite depuis [Google AI Studio](https://aistudio.google.com/). Sans cette clé, la newsletter fonctionne parfaitement avec les chiffres et les gros titres.

### 3. Tester immédiatement en 1 clic
Sur GitHub, va dans l'onglet **Actions** → **Weekly Market Discord Newsletter** → **Run workflow**.
Tu devrais recevoir la notification sur ton Discord dans les 20 secondes !

---

## Tester en local
```bash
python -m venv .venv
# Windows PowerShell :
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python src/newsletter.py --dry-run
```
