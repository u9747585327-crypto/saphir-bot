#!/bin/bash
# Déploiement automatique : toutes les minutes (auto-deploy.timer), chaque bot récupère
# ce qui a été poussé sur GitHub. S'il y a du nouveau : mise à jour, dépendances si
# requirements.txt a changé, redémarrage. Journal : journalctl -u auto-deploy
set -u
deployer() {
    local dir=$1 service=$2 python=$3
    local g="git -c safe.directory=$dir -C $dir"
    $g fetch -q origin main 2>&1 || { echo "[$service] fetch impossible"; return; }
    local avant apres
    avant=$($g rev-parse HEAD)
    apres=$($g rev-parse origin/main)
    [ "$avant" = "$apres" ] && return
    # un /rec en cours (repère posé par cogs/enregistrement.py) : on redémarrera après
    if compgen -G "$dir/data/enregistrements/actif-*" > /dev/null; then
        echo "[$service] enregistrement en cours : mise à jour reportée"; return
    fi
    # on ne touche à rien si des fichiers suivis ont été modifiés à la main sur le VPS
    if ! $g diff --quiet; then
        echo "[$service] modifications locales sur le VPS : mise à jour suspendue"; return
    fi
    if ! $g merge -q --ff-only origin/main; then
        echo "[$service] historique divergent : mise à jour suspendue"; return
    fi
    chown -R "$(stat -c %U "$dir")":"$(stat -c %G "$dir")" "$dir"
    if $g diff --name-only "$avant" "$apres" | grep -qx requirements.txt; then
        echo "[$service] requirements.txt modifié : installation des dépendances"
        runuser -u "$(stat -c %U "$dir")" -- "$python" -m pip install -q -r "$dir/requirements.txt" 2>&1 | grep -v notice
    fi
    systemctl restart "$service"
    echo "[$service] déployé : $($g log --oneline -1)"
}
deployer /opt/saphir-bot saphir-bot /opt/saphir-bot/.venv/bin/python
deployer /opt/lumi-bot lumi-bot /opt/lumi-bot/venv/bin/python
