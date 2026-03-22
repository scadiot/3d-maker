# Audit — 3D Maker
_Date : 2026-03-22_

---

## Critique

### 1. `HistoryManager._undo.pop(0)` est O(n)
**Fichier :** `editor/history.py` ligne 58

Quand l'historique est plein (max 100), `pop(0)` décale toute la liste à chaque nouvelle commande.
**Correction :** remplacer `list` par `collections.deque(maxlen=100)`.

---

### 2. Chemins absolus hardcodés
**Fichier :** `editor/constants.py` lignes 8–9

```python
TEXTURE_PATH = r"C:\Dev\Paris\assets\textures\atlas_1.png"
ATLAS_JSON   = r"C:\Dev\Paris\assets\textures\atlas_1.json"
```

L'application ne fonctionne que sur la machine de développement.
**Correction :** rendre ces chemins relatifs au répertoire du projet, ou les rendre configurables via un fichier de settings utilisateur.

---

### 3. `StateManager._emit` : événements ré-entrants silencieusement ignorés
**Fichier :** `editor/state_manager.py` lignes 360–368

Le flag `_emitting = True` bloque tout événement déclenché depuis un subscriber. Si une mutation dans un callback essaie d'émettre un autre événement (même d'un type différent), cet événement est **silencieusement perdu**. Très difficile à diagnostiquer.
**Correction :** utiliser une file d'attente par type d'événement, ou un compteur de profondeur (`_emit_depth`) plutôt qu'un booléen.

---

### 4. Aucune gestion d'erreur dans le serializer
**Fichier :** `editor/serializer.py` lignes 51–143

`load_json` et `import_json` n'ont aucun `try/except`. Un fichier JSON corrompu, un chemin d'atlas manquant, ou une clé absente lève une exception non interceptée et peut laisser la scène dans un état partiellement chargé (root modifié, selection incorrecte).
**Correction :** encapsuler le chargement dans un try/except, rétablir l'état initial en cas d'échec (pattern "tout ou rien").

---

### 5. `ctypes.windll` dans le hot path souris
**Fichier :** `editor/app.py` ligne 809

```python
ctypes.windll.user32.SetCursorPos(self.pan_anchor_x, self.pan_anchor_y)
```

Cette API est Windows-only. Toute la logique de panning au clic milieu est non-portable (macOS / Linux).
**Correction :** utiliser une abstraction conditionnelle ou la méthode Tkinter `event_generate` + `warp_pointer` selon la plateforme.

---

## Moyen

### 6. `all_polygons()` rappelé à chaque accès dans les vues de compatibilité
**Fichier :** `editor/scene.py` lignes 37–71

`_PolygonVertices._flat()` et `_PolyUVs._flat()` appellent `all_polygons(root)` à chaque `__getitem__`, `__len__`, etc., ce qui traverse tout l'arbre. Les fonctions `pick_polygon`, `pick_edge`, `pick_vertex` appellent également `all_polygons()` plusieurs fois chacune.
**Correction :** mettre en cache la liste plate et invalider le cache sur `scene_changed`.

---

### 7. `Polygon.texture_atlas_id` n'est pas dans le constructeur
**Fichier :** `editor/group.py` ligne 24

L'attribut `texture_atlas_id` est ajouté comme attribut d'instance après construction (`new_poly.texture_atlas_id = ...`), ce qui oblige chaque appelant à ne pas oublier de l'initialiser.
**Correction :** ajouter `texture_atlas_id: int = 0` comme paramètre du constructeur `Polygon.__init__`.

---

### 8. Deux chemins de suppression parallèles avec comportements différents
**Fichier :** `editor/scene.py` lignes 231–246 et `editor/state_manager.py` lignes 197–213

`scene.delete_selected()` nettoie les groupes vides sous root en plus de supprimer les polygones. `state.delete_polygons()` ne le fait pas. Le comportement observable dépend de qui appelle.
**Correction :** consolider la logique de nettoyage des groupes vides dans `state.delete_polygons()` et supprimer `scene.delete_selected()`.

---

### 9. `_emit` privé appelé directement hors de `StateManager`
**Fichiers :** `editor/history.py` ligne 128, `editor/scene.py` ligne 184, `editor/app.py` ligne 1042

Plusieurs modules appellent `self._state._emit(...)` directement, bypassant l'API publique et l'invariant `_modified = True` qui devrait systématiquement accompagner les mutations.
**Correction :** exposer des méthodes publiques dédiées dans `StateManager` pour les cas manquants, ou s'assurer que `_emit` est vraiment interne (convention `__emit`).

---

### 10. `scene.draw()` trie les polygones visibles à chaque frame
**Fichier :** `editor/scene.py` ligne 544

```python
visible.sort(key=lambda p: p.texture_atlas_id or '')
```

Ce tri est exécuté à ~60 fps. Pour une scène statique, c'est du travail inutile.
**Correction :** ajouter une dirty flag `_draw_order_dirty` invalidée sur `scene_changed`, et ne re-trier que quand nécessaire.

---

## Code quality

### 11. `screen_ray` normalise deux fois inutilement
**Fichier :** `editor/camera.py` ligne 49

La première `normalize((rcx, rcy, rcz))` est appliquée avant la rotation. Après rotation, le résultat est normalisé à nouveau. La première normalisation est redondante car la rotation (Euler) préserve la norme.

---

### 12. Les vues `_PolygonVertices` / `_PolyUVs` sont des shims obsolètes
**Fichier :** `editor/scene.py` lignes 28–71

Ces classes existent uniquement pour que `gizmo.py` puisse continuer à écrire `scene.polygons[i]`. Si `gizmo.py` utilise maintenant directement les objets `Polygon`, ces wrappers peuvent être supprimés, ce qui simplifiera le code et éliminera les traversées redondantes de l'arbre (cf. point 6).

---

### 13. `app.py` mélange trop de responsabilités
**Fichier :** `editor/app.py` (1022+ lignes)

Le fichier contient : construction de l'UI (menus, toolbars, panels, statusbar), gestion des événements souris et clavier, logique de toutes les commandes (duplicate, delete, group, split, extrude…), et dessin de la frame. Ce mélange rend les tests et l'évolution difficiles.
**Suggestion :** extraire un `InputHandler` (events), un `CommandController` (logique métier), et un `UIBuilder` (construction widgets).

---

### 14. `_sync_toolbar2_btns` repack/unpack des widgets à chaque `selection_changed`
**Fichier :** `editor/app.py` lignes 557–595

À chaque changement de sélection, des widgets sont `pack_forget()` puis `pack()`, provoquant un re-layout complet de la barre d'outils.
**Correction :** garder les widgets toujours packés et utiliser `widget.config(state='disabled')` + `widget.config(state='normal')` pour les masquer fonctionnellement, ou utiliser `grid` avec `columnconfigure`.

---

## Résumé

| Priorité | Problème | Fichier |
|----------|----------|---------|
| Critique | `pop(0)` O(n) dans l'historique | `history.py:58` |
| Critique | Chemins absolus hardcodés | `constants.py:8-9` |
| Critique | Événements ré-entrants silencieux | `state_manager.py:360` |
| Critique | Pas de try/except au chargement | `serializer.py:51` |
| Critique | API Windows-only dans le panning | `app.py:809` |
| Moyen | `all_polygons()` répété sans cache | `scene.py:37` |
| Moyen | `texture_atlas_id` hors constructeur | `group.py:24` |
| Moyen | Deux chemins delete incohérents | `scene.py:231` / `state_manager.py:197` |
| Moyen | `_emit` privé appelé de l'extérieur | `history.py:128`, `scene.py:184` |
| Moyen | Tri des polygones à chaque frame | `scene.py:544` |
| Qualité | Double normalisation dans `screen_ray` | `camera.py:49` |
| Qualité | Shims `_PolygonVertices`/`_PolyUVs` obsolètes | `scene.py:28` |
| Qualité | `app.py` trop large, responsabilités mélangées | `app.py` |
| Qualité | Re-layout toolbar à chaque sélection | `app.py:557` |
