# StateManager — Document de conception

## 1. Contexte et problèmes actuels

### 1.1 Architecture actuelle

L'état de la scène est actuellement **dispersé** dans plusieurs classes sans coordination centralisée :

| Classe | État détenu |
|--------|-------------|
| `App` | `current_group`, `selection_mode`, `selected_indices` (dupliqué) |
| `Scene` | `root`, `selected_idx`, `selected_indices`, `selected_edges`, `selected_edges_ordered`, `selected_vertices` |
| `Gizmo` | État de drag (volatile, pendant une interaction) |

### 1.2 Problèmes identifiés

1. **État dupliqué** : `selected_indices` existe à la fois dans `App` et dans `Scene`.
2. **Synchronisation fragile** : toute mutation déclenche des appels manuels (`_refresh_group_panel()`, `_sync_toolbar2_btns()`, `_sync_gizmo_btns()`, `refresh()`) susceptibles d'être oubliés.
3. **Couplage fort** : `GroupPanel` connaît `Scene` et `App`, `App` connaît `GroupPanel`, etc. Un changement de structure impacte plusieurs fichiers.
4. **Indices fragiles** : la sélection est stockée comme indices entiers dans une liste aplatie. Toute modification de la hiérarchie invalide ces indices et nécessite `_refresh_int_selections()`.
5. **Aucun système d'événements** : impossible d'ajouter un nouveau composant (ex: barre de statut, timeline) sans toucher aux classes existantes.

---

## 2. Objectif du StateManager

Le `StateManager` est la **source unique de vérité** (Single Source of Truth) pour l'état de la scène. Il :

- Centralise toutes les données significatives de la scène.
- Expose des **mutateurs** qui garantissent la cohérence interne avant de notifier.
- Notifie les abonnés via un **système d'observeurs** (pattern Observer).
- Ne contient **ni logique de rendu, ni logique d'UI** — uniquement de l'état et des règles de cohérence.

---

## 3. Patrons de conception utilisés

### 3.1 Observer (Observeur / Event Emitter)

Les composants s'abonnent à des événements nommés. Quand le `StateManager` mutate son état, il émet l'événement correspondant et tous les abonnés sont rappelés.

```
StateManager
  ├── subscribe("selection_changed", callback)
  ├── unsubscribe("selection_changed", callback)
  └── _emit("selection_changed", payload)
        ├── → GroupPanel.on_selection_changed()
        ├── → Viewport._refresh_gizmo()
        └── → Toolbar._sync_buttons()
```

### 3.2 Single Source of Truth (Redux-inspired)

Personne ne mutate directement les données — tout passe par le `StateManager`. Les composants ne font que **lire** l'état via les accesseurs ou **écouter** les événements.

### 3.3 Command Pattern (futur — Undo/Redo)

Chaque mutation peut être encapsulée dans une `Command` réversible. Le `StateManager` serait le bon endroit pour gérer la pile undo/redo. Cette couche n'est pas incluse dans la première implémentation mais l'API des mutateurs doit y être compatible (pas d'effets de bord implicites).

---

## 4. État centralisé

### 4.1 Données à gérer

```python
# Hiérarchie de la scène
root_group: Group          # Racine de l'arbre (jamais None)

# Navigation dans la hiérarchie
current_group: Group       # Groupe courant pour la création de polygones

# Sélection (par référence objet, non par indice)
selection_mode: SelectionMode          # 'polygon' | 'edge' | 'vertex'
selected_polygons: list[Polygon]       # Polygones sélectionnés
selected_edges: list[tuple[Polygon, int]]     # (polygone, indice_arête)
selected_vertices: list[tuple[Polygon, int]]  # (polygone, indice_vertex)
```

### 4.2 Ce qui N'appartient PAS au StateManager

| Donnée | Où elle reste |
|--------|---------------|
| Position/rotation caméra | `Camera` |
| État de drag gizmo | `Gizmo` (état volatile d'interaction) |
| Texture atlas | `Scene` ou dédié `TextureManager` |
| Taille fenêtre, état Tkinter | `App` |

### 4.3 Suppression des indices entiers

Actuellement, `selected_indices` est un `set[int]` indexant `all_polygons(root)`. Ce système est fragile car les indices changent quand la hiérarchie change.

**Nouveau principe :** la sélection est stockée par **référence objet** (`set[Polygon]`). Les indices entiers sont calculés **à la demande** via une propriété `selected_indices` pour compatibilité avec le `Gizmo` existant.

```python
@property
def selected_indices(self) -> list[int]:
    """Compatibilité Gizmo : indices dans all_polygons(root)."""
    all_polys = all_polygons(self.root_group)
    return [all_polys.index(p) for p in self.selected_polygons if p in all_polys]
```

---

## 5. Événements

### 5.1 Catalogue des événements

| Événement | Déclenché quand | Payload |
|-----------|----------------|---------|
| `scene_changed` | Structure de l'arbre modifiée (ajout, suppression, déplacement, renommage) | `change_type: str, **contexte` |
| `selection_changed` | Sélection modifiée | `polygons: list, edges: list, vertices: list, mode: str` |
| `current_group_changed` | Groupe courant changé | `group: Group` |
| `polygon_transformed` | Vertices d'un polygone modifiés (drag gizmo) | `polygons: list[Polygon]` |

### 5.2 Granularité de `scene_changed` — pattern `change_type`

`scene_changed` est **un seul événement** avec un champ `change_type` dans le payload. C'est le juste milieu entre un événement fourre-tout et une prolifération d'événements distincts — le même pattern que Redux (`action.type`) ou les événements DOM (`event.type`).

**Valeurs de `change_type` :**

| Valeur | Mutation correspondante | Contexte supplémentaire |
|--------|------------------------|------------------------|
| `"polygon_added"` | `add_polygon()` | `polygon: Polygon, group: Group` |
| `"polygons_deleted"` | `delete_polygons()` | `polygons: list[Polygon]` |
| `"polygon_moved"` | `move_polygon()` | `polygon: Polygon, new_group: Group` |
| `"group_added"` | `add_group()` | `group: Group, parent: Group` |
| `"group_deleted"` | `delete_group()` | `group: Group` |
| `"group_renamed"` | `rename_group()` | `group: Group, old_name: str` |
| `"group_moved"` | `move_group()` | `group: Group, new_parent: Group` |

**Avantages :**
- Un seul abonnement suffit pour réagir à tous les changements structurels.
- Les abonnés peuvent **optimiser** selon le cas sans gérer plusieurs canaux.
- Ajouter un nouveau `change_type` ne casse aucun abonné existant (ils ignorent les types inconnus).

```python
# Exemple d'abonné optimisé :
def _on_scene_changed(self, change_type: str, **kw):
    if change_type == "group_renamed":
        self._rename_item_only(kw["group"])   # mise à jour légère
    else:
        self.refresh()                         # reconstruction complète par défaut
```

`polygon_transformed` reste un événement séparé car il est émis à **chaque frame** pendant le drag — les abonnés (viewport) doivent re-rendre sans reconstruire l'UI.

---

## 6. API proposée

```python
from __future__ import annotations
from typing import Callable, Literal
from editor.group import Group, Polygon

SelectionMode = Literal["polygon", "edge", "vertex"]
EventName = Literal[
    "scene_changed",
    "selection_changed",
    "current_group_changed",
    "polygon_transformed",
]

class StateManager:

    # ------------------------------------------------------------------ #
    # Construction                                                         #
    # ------------------------------------------------------------------ #

    def __init__(self, root_group: Group) -> None: ...

    # ------------------------------------------------------------------ #
    # Accesseurs (lecture)                                                 #
    # ------------------------------------------------------------------ #

    @property
    def root_group(self) -> Group: ...

    @property
    def current_group(self) -> Group: ...

    @property
    def selection_mode(self) -> SelectionMode: ...

    @property
    def selected_polygons(self) -> list[Polygon]: ...

    @property
    def selected_edges(self) -> list[tuple[Polygon, int]]: ...

    @property
    def selected_vertices(self) -> list[tuple[Polygon, int]]: ...

    # Compatibilité avec le code existant (Gizmo, Scene)
    @property
    def selected_indices(self) -> list[int]: ...

    # ------------------------------------------------------------------ #
    # Mutateurs scène                                                      #
    # ------------------------------------------------------------------ #

    def add_polygon(self, polygon: Polygon, group: Group | None = None) -> None:
        """Ajoute un polygone au groupe donné (ou current_group par défaut)."""

    def delete_polygons(self, polygons: list[Polygon]) -> None:
        """Supprime les polygones de la scène et met à jour la sélection."""

    def move_polygon(self, polygon: Polygon, new_group: Group) -> None:
        """Déplace un polygone vers un autre groupe."""

    def add_group(self, name: str, parent: Group | None = None) -> Group:
        """Crée un nouveau groupe enfant."""

    def delete_group(self, group: Group) -> None:
        """Supprime un groupe et tous ses enfants."""

    def rename_group(self, group: Group, name: str) -> None:
        """Renomme un groupe."""

    def move_group(self, group: Group, new_parent: Group) -> None:
        """Déplace un groupe dans la hiérarchie."""

    def notify_polygon_transformed(self, polygons: list[Polygon]) -> None:
        """À appeler par le Gizmo après chaque frame de drag."""

    # ------------------------------------------------------------------ #
    # Mutateurs sélection                                                  #
    # ------------------------------------------------------------------ #

    def set_selection(
        self,
        polygons: list[Polygon] | None = None,
        edges: list[tuple[Polygon, int]] | None = None,
        vertices: list[tuple[Polygon, int]] | None = None,
    ) -> None:
        """Remplace toute la sélection. Passer None conserve la valeur actuelle."""

    def clear_selection(self) -> None:
        """Vide la sélection complètement."""

    def set_selection_mode(self, mode: SelectionMode) -> None:
        """Change le mode de sélection et vide la sélection incompatible."""

    def set_current_group(self, group: Group) -> None:
        """Change le groupe courant."""

    # ------------------------------------------------------------------ #
    # Système d'observeurs                                                 #
    # ------------------------------------------------------------------ #

    def subscribe(self, event: EventName, callback: Callable) -> None:
        """Abonne callback à l'événement. Idempotent."""

    def unsubscribe(self, event: EventName, callback: Callable) -> None:
        """Désabonne callback. Ne lève pas d'erreur si absent."""
```

---

## 7. Implémentation du système d'observeurs

```python
from collections import defaultdict

class StateManager:
    def __init__(self, root_group: Group) -> None:
        self._root_group = root_group
        self._current_group = root_group
        self._selection_mode: SelectionMode = "polygon"
        self._selected_polygons: list[Polygon] = []
        self._selected_edges: list[tuple[Polygon, int]] = []
        self._selected_vertices: list[tuple[Polygon, int]] = []
        self._listeners: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event: str, callback: Callable) -> None:
        if callback not in self._listeners[event]:
            self._listeners[event].append(callback)

    def unsubscribe(self, event: str, callback: Callable) -> None:
        self._listeners[event] = [
            cb for cb in self._listeners[event] if cb != callback
        ]

    def _emit(self, event: str, **payload) -> None:
        for callback in list(self._listeners[event]):
            callback(**payload)
```

**Règle :** `_emit` est toujours appelé **après** la mutation, jamais avant, afin que les abonnés lisent un état cohérent.

---

## 8. Stratégie de migration

La migration se fait en **phases incrémentales** sans casser l'existant.

### Phase 1 — Création du StateManager (non intrusif)

- Créer `editor/state_manager.py` avec la classe `StateManager`.
- Instancier dans `App.__init__` : `self.state = StateManager(self.scene.root)`.
- Aucun autre fichier modifié.

### Phase 2 — Migration de la sélection

- Déplacer `selected_polygons`, `selected_edges`, `selected_vertices` de `Scene` vers `StateManager`.
- Garder des propriétés de compatibilité dans `Scene` qui délèguent au `StateManager`.
- Migrer `GroupPanel.sync_selection()` pour s'abonner à `selection_changed`.

### Phase 3 — Migration du groupe courant

- Déplacer `App.current_group` vers `StateManager.current_group`.
- Migrer les abonnés (`GroupPanel`, `App._add_polygon_from_*`).

### Phase 4 — Migration des mutations scène

- Envelopper les mutations structurelles dans les mutateurs du `StateManager`.
- Supprimer les appels manuels à `_refresh_group_panel()`.

### Phase 5 — Nettoyage

- Supprimer l'état dupliqué dans `Scene` et `App`.
- Supprimer `_refresh_int_selections()` (plus besoin d'indices fragiles).

---

## 9. Exemple d'intégration : GroupPanel

**Avant :**
```python
# Dans App, après une suppression :
self.scene.delete_selected()
self._refresh_group_panel()   # appel manuel
self._sync_toolbar2_btns()    # appel manuel
```

**Après :**
```python
# GroupPanel s'abonne une fois à l'init :
self.state.subscribe("scene_changed", self._on_scene_changed)
self.state.subscribe("selection_changed", self._on_selection_changed)

# Dans App, après une suppression :
self.state.delete_polygons(self.state.selected_polygons)
# → StateManager émet "scene_changed" et "selection_changed"
# → GroupPanel.refresh() appelé automatiquement
# → Toolbar._sync_buttons() appelé automatiquement
```

---

## 10. Compatibilité avec le Gizmo

Le `Gizmo` travaille actuellement avec des indices entiers et un accès direct aux vertices. Deux options :

**Option A (recommandée) :** Conserver l'interface actuelle du `Gizmo`, qui appelle `notify_polygon_transformed()` sur le `StateManager` à chaque frame. Le `StateManager` n'est pas dans la boucle de calcul — il est seulement notifié.

**Option B :** Refactorer le `Gizmo` pour travailler par références objet. Plus propre, mais scope plus large, à faire séparément.

---

## 11. Risques et points d'attention

| Risque | Mitigation |
|--------|-----------|
| Boucles de notification (A notifie B qui notifie A) | Flag `_emitting: bool` pour ignorer les émissions récursives |
| Performance pendant le drag (polygon_transformed à 60fps) | Abonnés à `polygon_transformed` doivent être rapides (pas de rebuild UI complet) |
| Migration partielle = double source de vérité temporaire | Documenter clairement les phases, ne pas laisser l'état dupliqué plus d'une phase |
| Références d'objets invalidées (Polygon supprimé) | Les mutateurs nettoient la sélection avant d'émettre |

---

## 12. Fichiers impactés

| Fichier | Nature de la modification |
|---------|--------------------------|
| `editor/state_manager.py` | **Nouveau fichier** à créer |
| `editor/app.py` | Instanciation du StateManager, suppression de `current_group` et `selected_indices` |
| `editor/scene.py` | Suppression des champs de sélection, délégation au StateManager |
| `editor/group_panel.py` | Remplacement des appels manuels par des abonnements |
| `editor/gizmo.py` | Appel à `notify_polygon_transformed()` après chaque drag |
| `main.py` | Aucun changement |

---

## Todo

- [x] **[Conception]** Valider le catalogue d'événements — décision : `scene_changed` unique avec `change_type` dans le payload (pattern Redux/DOM)
- [x] **[Conception]** Décider si `SelectionMode` doit être dans `StateManager` — décision : **oui**, `selection_mode` intégré au StateManager
- [x] **[Phase 1]** Créer `editor/state_manager.py` avec la classe vide et le système d'observeurs
- [x] **[Phase 1]** Écrire des tests unitaires pour le mécanisme subscribe/unsubscribe/emit
- [x] **[Phase 2]** Migrer `selected_polygons`, `selected_edges`, `selected_vertices` de `Scene` vers `StateManager`
- [x] **[Phase 2]** Ajouter propriétés de compatibilité dans `Scene` (pour ne pas casser le Gizmo)
- [x] **[Phase 2]** Migrer `GroupPanel.sync_selection()` → abonnement à `selection_changed`
- [x] **[Phase 3]** Migrer `App.current_group` → `StateManager.current_group`
- [x] **[Phase 3]** Abonner `GroupPanel` à `current_group_changed`
- [x] **[Phase 4]** Envelopper `scene.delete_selected()`, `add_polygon()`, etc. dans les mutateurs du StateManager
- [x] **[Phase 4]** Supprimer les appels manuels `_refresh_group_panel()`, `_sync_toolbar2_btns()` dans `App`
- [x] **[Phase 5]** Supprimer l'état dupliqué dans `Scene` et `App`
- [x] **[Phase 5]** Supprimer `_refresh_int_selections()` et remplacer par le calcul à la demande
- [ ] **[Futur]** Évaluer l'ajout du Command Pattern pour undo/redo (l'API des mutateurs y est déjà compatible)
- [ ] **[Futur]** Refactorer le `Gizmo` pour travailler par référence objet plutôt que par indices
