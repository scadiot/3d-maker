"""Tests unitaires — StateManager : subscribe / unsubscribe / emit."""

import pytest
from editor.group import Group, Polygon
from editor.state_manager import StateManager


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def root():
    return Group("Racine")


@pytest.fixture
def sm(root):
    return StateManager(root)


def make_polygon(group=None):
    verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    uvs   = [(0, 0), (1, 0), (1, 1), (0, 1)]
    return Polygon(verts, uvs, group=group)


# ── subscribe / unsubscribe ───────────────────────────────────────────────────

class TestSubscribe:
    def test_callback_appelé_à_lémission(self, sm):
        reçu = []
        sm.subscribe("selection_changed", lambda **kw: reçu.append(kw))
        sm.clear_selection()
        assert len(reçu) == 1

    def test_subscribe_idempotent(self, sm):
        reçu = []
        cb = lambda **kw: reçu.append(kw)
        sm.subscribe("selection_changed", cb)
        sm.subscribe("selection_changed", cb)  # double abonnement
        sm.clear_selection()
        assert len(reçu) == 1  # appelé une seule fois

    def test_plusieurs_abonnés_tous_notifiés(self, sm):
        reçu = []
        sm.subscribe("selection_changed", lambda **kw: reçu.append("a"))
        sm.subscribe("selection_changed", lambda **kw: reçu.append("b"))
        sm.clear_selection()
        assert sorted(reçu) == ["a", "b"]

    def test_abonnement_à_événement_différent_non_notifié(self, sm):
        reçu = []
        sm.subscribe("scene_changed", lambda **kw: reçu.append(kw))
        sm.clear_selection()  # émet selection_changed, pas scene_changed
        assert reçu == []


class TestUnsubscribe:
    def test_désabonnement_stoppe_notifications(self, sm):
        reçu = []
        cb = lambda **kw: reçu.append(kw)
        sm.subscribe("selection_changed", cb)
        sm.unsubscribe("selection_changed", cb)
        sm.clear_selection()
        assert reçu == []

    def test_unsubscribe_absent_ne_lève_pas(self, sm):
        cb = lambda **kw: None
        sm.unsubscribe("selection_changed", cb)  # pas abonné → pas d'erreur

    def test_unsubscribe_retire_seulement_le_bon_callback(self, sm):
        reçu = []
        cb_a = lambda **kw: reçu.append("a")
        cb_b = lambda **kw: reçu.append("b")
        sm.subscribe("selection_changed", cb_a)
        sm.subscribe("selection_changed", cb_b)
        sm.unsubscribe("selection_changed", cb_a)
        sm.clear_selection()
        assert reçu == ["b"]

    def test_unsubscribe_puis_reabonnement(self, sm):
        reçu = []
        cb = lambda **kw: reçu.append(kw)
        sm.subscribe("selection_changed", cb)
        sm.unsubscribe("selection_changed", cb)
        sm.subscribe("selection_changed", cb)
        sm.clear_selection()
        assert len(reçu) == 1


# ── Payload des événements ────────────────────────────────────────────────────

class TestPayload:
    def test_selection_changed_payload(self, sm):
        reçu = []
        sm.subscribe("selection_changed", lambda **kw: reçu.append(kw))
        sm.clear_selection()
        payload = reçu[0]
        assert "polygons" in payload
        assert "edges" in payload
        assert "vertices" in payload
        assert "mode" in payload

    def test_scene_changed_payload_polygon_added(self, sm, root):
        reçu = []
        sm.subscribe("scene_changed", lambda **kw: reçu.append(kw))
        poly = make_polygon()
        sm.add_polygon(poly, root)
        assert reçu[0]["change_type"] == "polygon_added"
        assert reçu[0]["polygon"] is poly
        assert reçu[0]["group"] is root

    def test_scene_changed_payload_polygons_deleted(self, sm, root):
        reçu = []
        poly = make_polygon()
        sm.add_polygon(poly, root)
        sm.subscribe("scene_changed", lambda **kw: reçu.append(kw))
        sm.delete_polygons([poly])
        assert reçu[0]["change_type"] == "polygons_deleted"
        assert poly in reçu[0]["polygons"]

    def test_scene_changed_payload_group_added(self, sm, root):
        reçu = []
        sm.subscribe("scene_changed", lambda **kw: reçu.append(kw))
        grp = sm.add_group("Enfant", root)
        assert reçu[0]["change_type"] == "group_added"
        assert reçu[0]["group"] is grp
        assert reçu[0]["parent"] is root

    def test_scene_changed_payload_group_renamed(self, sm, root):
        reçu = []
        grp = sm.add_group("Ancien", root)
        sm.subscribe("scene_changed", lambda **kw: reçu.append(kw))
        sm.rename_group(grp, "Nouveau")
        assert reçu[0]["change_type"] == "group_renamed"
        assert reçu[0]["old_name"] == "Ancien"
        assert grp.name == "Nouveau"

    def test_current_group_changed_payload(self, sm, root):
        reçu = []
        grp = sm.add_group("Enfant", root)
        sm.subscribe("current_group_changed", lambda **kw: reçu.append(kw))
        sm.set_current_group(grp)
        assert reçu[0]["group"] is grp

    def test_polygon_transformed_payload(self, sm, root):
        reçu = []
        poly = make_polygon()
        sm.add_polygon(poly, root)
        sm.subscribe("polygon_transformed", lambda **kw: reçu.append(kw))
        sm.notify_polygon_transformed([poly])
        assert reçu[0]["polygons"] == [poly]


# ── Garde anti-boucle ─────────────────────────────────────────────────────────

class TestGardeAntiBoucle:
    def test_emission_récursive_ignorée(self, sm):
        """Un callback qui tente d'émettre ne provoque pas de boucle infinie."""
        compteur = {"n": 0}

        def cb(**kw):
            compteur["n"] += 1
            sm.clear_selection()  # tente une émission récursive

        sm.subscribe("selection_changed", cb)
        sm.clear_selection()
        assert compteur["n"] == 1  # appelé une seule fois, pas en boucle


# ── Mutateurs sélection ───────────────────────────────────────────────────────

class TestMutateursSélection:
    def test_set_selection_émet_selection_changed(self, sm, root):
        reçu = []
        poly = make_polygon()
        root.adopt_polygon(poly)
        sm.subscribe("selection_changed", lambda **kw: reçu.append(kw))
        sm.set_selection(polygons=[poly])
        assert len(reçu) == 1
        assert reçu[0]["polygons"] == [poly]

    def test_set_selection_none_conserve_valeur(self, sm, root):
        poly = make_polygon()
        root.adopt_polygon(poly)
        sm.set_selection(polygons=[poly])
        sm.set_selection(edges=[(poly, 0)])  # polygons=None → conservé
        assert sm.selected_polygons == [poly]
        assert sm.selected_edges == [(poly, 0)]

    def test_set_selection_mode_vide_sélection_incompatible(self, sm, root):
        poly = make_polygon()
        root.adopt_polygon(poly)
        sm.set_selection(polygons=[poly])
        sm.set_selection_mode("edge")
        assert sm.selected_polygons == []
        assert sm.selection_mode == "edge"

    def test_set_selection_mode_identique_néémet_pas(self, sm):
        reçu = []
        sm.subscribe("selection_changed", lambda **kw: reçu.append(kw))
        sm.set_selection_mode("polygon")  # déjà "polygon" par défaut
        assert reçu == []

    def test_set_current_group_émet(self, sm, root):
        reçu = []
        grp = sm.add_group("Enfant", root)
        sm.subscribe("current_group_changed", lambda **kw: reçu.append(kw))
        sm.set_current_group(grp)
        assert len(reçu) == 1

    def test_set_current_group_identique_néémet_pas(self, sm, root):
        reçu = []
        sm.subscribe("current_group_changed", lambda **kw: reçu.append(kw))
        sm.set_current_group(root)  # déjà root par défaut
        assert reçu == []


# ── selected_indices (compatibilité Gizmo) ────────────────────────────────────

class TestSelectedIndices:
    def test_indices_corrects(self, sm, root):
        p0 = make_polygon(); root.adopt_polygon(p0)
        p1 = make_polygon(); root.adopt_polygon(p1)
        p2 = make_polygon(); root.adopt_polygon(p2)
        sm.set_selection(polygons=[p0, p2])
        assert sm.selected_indices == [0, 2]

    def test_indices_vides_si_aucune_sélection(self, sm):
        assert sm.selected_indices == []

    def test_indices_après_suppression(self, sm, root):
        p0 = make_polygon(); root.adopt_polygon(p0)
        p1 = make_polygon(); root.adopt_polygon(p1)
        sm.set_selection(polygons=[p0, p1])
        sm.delete_polygons([p0])
        assert sm.selected_indices == [0]  # p1 est maintenant à l'indice 0
