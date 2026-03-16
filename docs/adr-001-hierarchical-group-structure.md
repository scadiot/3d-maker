# ADR-001 : Structure hiérarchique de groupes pour les polygones

**Date** : 2026-03-16
**Statut** : Accepté

---

## Contexte

La scène stockait les polygones et leurs UVs dans deux listes plates parallèles :

```python
self.polygons : List[List[Tuple[float, float, float]]]
self.poly_uvs : List[List[Tuple[float, float]]]
```

La synchronisation entre ces deux listes était fragile (le même indice `i` devait désigner le même polygone dans les deux listes). Les groupes étaient gérés séparément via `self.groups : List[Set[int]]`, une liste de sets d'indices — ce qui rendait la relation polygone↔groupe indirecte et difficile à maintenir.

Cette structure ne permettait pas de représenter une hiérarchie d'objets (groupes imbriqués), ce qui limite les futures fonctionnalités (organisation de la scène, sélection par groupe, import/export structuré).

---

## Décision

Remplacer les listes plates par une **structure arborescente** basée sur deux nouvelles classes : `Polygon` et `Group`.

### Classes

```python
class Polygon:
    vertices : List[Tuple[float, float, float]]
    uvs      : List[Tuple[float, float]]
    group    : 'Group'   # référence vers le groupe parent

class Group:
    name     : str
    parent   : Optional['Group']   # None uniquement pour la racine
    children : List[Union['Group', Polygon]]
```

### Règles

- Un polygone appartient à **exactement un groupe**.
- La scène possède un `root : Group` qui est le groupe racine.
- La sélection est **inter-groupes** : on peut sélectionner des polygones appartenant à des groupes différents simultanément.

### Sélection

Les sélections utilisent des **références d'objets** Python plutôt que des indices :

```python
# Avant
selected_idx      : int
selected_indices  : Set[int]
selected_edges    : Set[Tuple[int, int]]   # (poly_idx, edge_idx)
selected_vertices : Set[Tuple[int, int]]   # (poly_idx, vertex_idx)

# Après
selected_polygons : Set[Polygon]
selected_edges    : Set[Tuple[Polygon, int]]
selected_vertices : Set[Tuple[Polygon, int]]
```

---

## Conséquences

### Avantages

- **Encapsulation** : vertices et UVs sont colocalisés dans `Polygon`, plus de synchronisation entre deux listes parallèles.
- **Hiérarchie naturelle** : les groupes imbriqués remplacent `self.groups : List[Set[int]]`.
- **Sélection plus lisible** : les références d'objets sont plus explicites que des tuples d'indices.
- **Extensibilité** : ajouter un nom, une visibilité, un matériau à un `Polygon` ou `Group` devient trivial.

### Points d'impact

| Zone | Changement |
|------|------------|
| `scene.py` | `polygons`, `poly_uvs`, `groups` remplacés par `root: Group` |
| `app.py` | Toute la logique de picking et sélection |
| `gizmo.py` | `drag_start_verts_all: Dict[Polygon, List[vertex]]` |
| `scene.draw()` | Traversée récursive au lieu de `enumerate(polygons)` |
| Save / Load | Format JSON hiérarchique |

### Contraintes acceptées

- Un polygone ne peut appartenir qu'à un seul groupe (pas de multi-appartenance).
- Le format de sauvegarde JSON change — les anciens fichiers `.json` devront être migrés.

---

## Plan de migration

| Étape | Description | Fichiers touchés |
|-------|-------------|-----------------|
| 1 | Créer `Polygon`, `Group` et les helpers de traversal (`iter_polygons`, `all_polygons`) | `editor/group.py` (nouveau) |
| 2 | Migrer `Scene` : remplacer les listes plates par `root: Group` | `editor/scene.py` |
| 3 | Migrer la sélection | `editor/app.py` |
| 4 | Migrer le gizmo et le rendu | `editor/gizmo.py`, `editor/scene.py` |
