"""Persistance des analyses (§20, §21, §24 du cahier des charges).

Prototype : SQLite (stdlib, zéro dépendance, fichier unique). PostgreSQL est
« envisagé » par le cahier des charges — la bascule ne concernera que ce
module : `routes.py` n'utilise que save_analysis / list_history / get_analysis.

Chaque analyse conserve (§24) : le résultat complet (payload JSON), la date
et la version du moteur. Les photos ne sont PAS stockées par défaut (§25 :
gestion de la conservation) — seules des métadonnées du traitement.

La base vit dans RITA_DB_PATH (défaut : data/rita.sqlite), créée à la volée.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

_DEFAULT_DB = Path(os.getenv('RITA_DB_PATH', 'data/rita.sqlite'))
_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id          TEXT PRIMARY KEY,
    created_at  REAL NOT NULL,
    version     TEXT NOT NULL,
    image_name  TEXT,
    marque      TEXT,
    objet       TEXT,
    modele      TEXT,
    decision    TEXT,
    code_top    TEXT,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analyses_date ON analyses(created_at DESC);
"""
_lock = threading.Lock()


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or _DEFAULT_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def save_analysis(payload: dict, image_name: str = '', db_path: Path | None = None) -> str:
    """Stocke le résultat complet d'une analyse et retourne son identifiant."""
    aid = uuid.uuid4().hex[:12]
    produit = payload.get('produit') or {}
    candidats = payload.get('candidats') or []
    classement = payload.get('classement') or {}
    top = (classement.get('candidats') or [{}])[0] if classement.get('candidats') else {}
    row = {
        'id': aid,
        'created_at': time.time(),
        'version': str((payload.get('meta') or {}).get('version') or ''),
        'image_name': str(image_name or ''),
        'marque': str(produit.get('marque') or ''),
        'objet': str(produit.get('objet') or ''),
        'modele': str(produit.get('modele_candidate') or ''),
        'decision': str((payload.get('decision_candidat') or {}).get('statut') or ''),
        'code_top': str(top.get('code') or ''),
        'payload': json.dumps(payload, ensure_ascii=False),
    }
    with _lock, _connect(db_path) as conn:
        conn.execute(
            'INSERT INTO analyses (id, created_at, version, image_name, marque, objet, modele, decision, code_top, payload) '
            'VALUES (:id, :created_at, :version, :image_name, :marque, :objet, :modele, :decision, :code_top, :payload)',
            row,
        )
    return aid


def list_history(limit: int = 20, db_path: Path | None = None) -> list[dict]:
    """Historique des analyses (§20 GET /history) : lignes résumées, plus récentes d'abord."""
    limit = max(1, min(int(limit), 100))
    with _lock, _connect(db_path) as conn:
        rows = conn.execute(
            'SELECT id, created_at, version, image_name, marque, objet, modele, decision, code_top '
            'FROM analyses ORDER BY created_at DESC LIMIT ?', (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_analysis(aid: str, db_path: Path | None = None) -> dict | None:
    """Récupère une analyse complète (§20 GET /analysis/{id})."""
    with _lock, _connect(db_path) as conn:
        row = conn.execute('SELECT payload FROM analyses WHERE id = ?', (str(aid or ''),)).fetchone()
    if not row:
        return None
    return json.loads(row['payload'])
