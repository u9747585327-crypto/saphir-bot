#!/usr/bin/env bash
# Installe / met a jour Saphir sur un VPS IONOS (Ubuntu ou Debian).
#
#   sudo bash deploy/install-ionos.sh
#
# Idempotent : relancer le script met simplement le code a jour et redemarre
# le service. Le fichier .env n'est jamais ecrase.

set -euo pipefail

NAME="saphir-bot"
REPO="https://github.com/u9747585327-crypto/saphir-bot.git"
APP_DIR="/opt/$NAME"
SERVICE_USER="saphir-bot"
UNIT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$NAME.service"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
die() { printf '\n\033[1;31mErreur : %s\033[0m\n' "$1" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "a lancer en root (sudo bash deploy/install-ionos.sh)"

log "Paquets systeme"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python3 python3-venv python3-pip sqlite3 ca-certificates

PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)')
[[ "$PY_OK" == "1" ]] || die "Python 3.10+ requis, trouve $(python3 -V)"
log "Python detecte : $(python3 -V)"

log "Utilisateur systeme $SERVICE_USER"
id -u "$SERVICE_USER" &>/dev/null || useradd --system --create-home --home-dir "/home/$SERVICE_USER" --shell /usr/sbin/nologin "$SERVICE_USER"

log "Code source dans $APP_DIR"
# Le dossier appartient a l'utilisateur du service, pas a root : sans cette
# option, git refuse d'y toucher ("detected dubious ownership").
GIT=(git -c safe.directory="$APP_DIR" -C "$APP_DIR")

if [[ -d "$APP_DIR/.git" ]]; then
  "${GIT[@]}" fetch --quiet origin
  "${GIT[@]}" reset --hard --quiet origin/main
else
  rm -rf "$APP_DIR"
  git clone --quiet "$REPO" "$APP_DIR"
fi
mkdir -p "$APP_DIR/data"

log "Environnement virtuel + dependances"
[[ -d "$APP_DIR/.venv" ]] || python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

NEEDS_ENV=0
if [[ ! -f "$APP_DIR/.env" ]]; then
  log "Creation du fichier .env (a remplir)"
  cat > "$APP_DIR/.env" <<'ENVEOF'
DISCORD_TOKEN=
GROQ_API_KEY=

# Stockage : SQLite dans data/saphir.db par defaut, rien a configurer.
# Decommente MONGODB_URI uniquement pour utiliser une base distante a la place.
#MONGODB_URI=
ENVEOF
  NEEDS_ENV=1
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"

log "Service systemd"
[[ -f "$UNIT_SRC" ]] || die "unit introuvable : $UNIT_SRC"
install -m 644 "$UNIT_SRC" "/etc/systemd/system/$NAME.service"
systemctl daemon-reload
systemctl enable --quiet "$NAME"

if [[ "$NEEDS_ENV" == "1" ]]; then
  cat <<MSG

  Installation terminee, mais le bot n'est PAS encore demarre.

  1. Renseigne les cles :   nano $APP_DIR/.env
  2. Demarre le service :   systemctl start $NAME
  3. Verifie les logs :     journalctl -u $NAME -f

MSG
else
  log "Redemarrage du service"
  systemctl restart "$NAME"
  sleep 3
  systemctl --no-pager --lines=0 status "$NAME" || true
  cat <<MSG

  A jour. Logs en direct :  journalctl -u $NAME -f

MSG
fi
