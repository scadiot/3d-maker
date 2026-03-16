"""Panneau hiérarchique des groupes avec drag & drop."""

import tkinter as tk
from tkinter import ttk

from editor.group import Group, Polygon, all_polygons


class GroupPanel(tk.Frame):
    """Affiche l'arbre Scène→Groupes→Polygones avec drag & drop entre nœuds."""

    _BG      = '#1a1a21'
    _BG_TREE = '#111118'
    _FG      = '#c8c8d8'
    _SEL_BG  = '#2d4080'
    _BTN_BG  = '#16161f'
    _BTN_ACT = '#2a2a3a'

    def __init__(self, master, scene, app):
        super().__init__(master, bg=self._BG)
        self._scene = scene
        self._app   = app
        self._iid_to_obj: dict = {}
        self._drag_iids: list = []
        self._drag_objs: list = []
        self._drop_iid        = None
        self._syncing         = False
        self._build()

    # ── Construction ──────────────────────────────────────────────────────────

    def _build(self):
        # Barre d'outils
        toolbar = tk.Frame(self, bg=self._BTN_BG)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        def make_btn(text, cmd):
            b = tk.Button(
                toolbar, text=text, command=cmd,
                bg=self._BTN_BG, fg=self._FG,
                activebackground=self._BTN_ACT, activeforeground=self._FG,
                relief='flat', bd=0, font=('Segoe UI', 12), width=3,
                cursor='hand2',
            )
            b.pack(side=tk.LEFT, padx=2, pady=2)
            b.bind('<Enter>', lambda _e, b=b: b.config(bg=self._BTN_ACT))
            b.bind('<Leave>', lambda _e, b=b: b.config(bg=self._BTN_BG))
            return b

        make_btn('+', self._add_group)
        make_btn('−', self._delete_selected)

        tk.Frame(self, height=1, bg='#2a2a3a').pack(side=tk.TOP, fill=tk.X)

        # Treeview
        tree_frame = tk.Frame(self, bg=self._BG_TREE)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        style = ttk.Style()
        style.theme_use('clam')
        style.configure(
            'GP.Treeview',
            background=self._BG_TREE,
            foreground=self._FG,
            fieldbackground=self._BG_TREE,
            borderwidth=0,
            font=('Segoe UI', 9),
            rowheight=22,
        )
        style.map(
            'GP.Treeview',
            background=[('selected', self._SEL_BG)],
            foreground=[('selected', self._FG)],
        )

        self._tree = ttk.Treeview(
            tree_frame, show='tree', selectmode='extended',
            style='GP.Treeview',
        )
        vsb = ttk.Scrollbar(tree_frame, orient='vertical',
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._tree.bind('<ButtonPress-1>',   self._on_drag_start)
        self._tree.bind('<B1-Motion>',       self._on_drag_motion)
        self._tree.bind('<ButtonRelease-1>', self._on_drag_end)
        self._tree.bind('<<TreeviewSelect>>', self._on_select)
        self._tree.bind('<Double-ButtonPress-1>', self._on_double_click)
        self._tree.bind('<ButtonPress-3>',   self._on_right_click)

        self.refresh()

    # ── Rafraîchissement ──────────────────────────────────────────────────────

    def refresh(self):
        """Reconstruit l'arbre depuis scene.root."""
        self._iid_to_obj.clear()
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        self._insert_group(self._scene.root, '')

    def _insert_group(self, group: Group, parent_iid: str):
        text = '⬡ Scène' if group.is_root else f'▶ {group.name}'
        iid  = self._tree.insert(parent_iid, 'end', text=text, open=True)
        self._iid_to_obj[iid] = group
        for child in group.children:
            self._insert_group(child, iid)
        for poly in group.polygons:
            self._insert_polygon(poly, iid)

    def _insert_polygon(self, poly: Polygon, parent_iid: str):
        flat  = all_polygons(self._scene.root)
        try:
            idx   = flat.index(poly)
            label = f'  ◆ Polygon {idx}'
        except ValueError:
            label = '  ◆ Polygon ?'
        iid = self._tree.insert(parent_iid, 'end', text=label)
        self._iid_to_obj[iid] = poly

    # ── Boutons ───────────────────────────────────────────────────────────────

    def _add_group(self):
        """Crée un sous-groupe dans le groupe sélectionné (ou root)."""
        sel = self._tree.selection()
        if sel:
            obj = self._iid_to_obj.get(sel[0])
            if isinstance(obj, Group):
                parent_group = obj
            else:
                parent_group = obj.group if obj.group else self._scene.root
        else:
            parent_group = self._scene.root
        parent_group.add_group('Groupe')
        self.refresh()

    def _delete_selected(self):
        """Supprime le groupe (et tous ses enfants) ou le polygon sélectionné."""
        sel = self._tree.selection()
        if not sel:
            return
        obj = self._iid_to_obj.get(sel[0])
        if obj is None or (isinstance(obj, Group) and obj.is_root):
            return

        old_flat = all_polygons(self._scene.root)
        if isinstance(obj, Group):
            obj.parent.remove_group(obj)
        else:
            if obj.group is not None:
                obj.group.remove_polygon(obj)

        self._scene._refresh_int_selections(old_flat)
        self.refresh()

    # ── Drag & drop ───────────────────────────────────────────────────────────

    def _on_drag_start(self, event):
        iid = self._tree.identify_row(event.y)
        if not iid:
            self._drag_iids = []
            return
        obj = self._iid_to_obj.get(iid)
        if isinstance(obj, Group) and obj.is_root:
            self._drag_iids = []
            return

        # Si le clic est sur un item déjà sélectionné, on drage toute la sélection
        sel = self._tree.selection()
        if iid in sel:
            candidates = list(sel)
        else:
            candidates = [iid]

        # Filtrer : pas de racine, pas de doublons
        self._drag_iids = [
            i for i in candidates
            if not (isinstance(self._iid_to_obj.get(i), Group)
                    and self._iid_to_obj[i].is_root)
        ]
        self._drag_objs = [self._iid_to_obj[i] for i in self._drag_iids]

    def _on_drag_motion(self, event):
        if not self._drag_iids:
            return
        self._tree.config(cursor='exchange')

    def _on_drag_end(self, event):
        self._tree.config(cursor='')
        if not self._drag_iids:
            return

        target_iid  = self._tree.identify_row(event.y)
        drag_iids   = self._drag_iids
        drag_objs   = self._drag_objs
        self._drag_iids = []
        self._drag_objs = []

        if not target_iid or target_iid in drag_iids:
            return

        target_obj = self._iid_to_obj.get(target_iid)
        if target_obj is None:
            return

        # Groupe cible : le groupe lui-même, ou le groupe du polygon cible
        target_group = (target_obj if isinstance(target_obj, Group)
                        else (target_obj.group or self._scene.root))

        old_flat = all_polygons(self._scene.root)
        moved = False
        for drag_obj in drag_objs:
            if isinstance(drag_obj, Group):
                # Anti-cycle : pas de déplacement dans soi-même ou ses descendants
                if drag_obj is target_group or self._is_ancestor(drag_obj, target_group):
                    continue
                if drag_obj.parent is target_group:
                    continue
                target_group.adopt_group(drag_obj)
                moved = True
            else:
                if drag_obj.group is target_group:
                    continue
                target_group.adopt_polygon(drag_obj)
                moved = True

        if moved:
            self._scene._refresh_int_selections(old_flat)
            self.refresh()

    def sync_selection(self, indices: set):
        """Met à jour la sélection du treeview depuis les indices de la scène."""
        if self._syncing:
            return
        flat           = all_polygons(self._scene.root)
        selected_polys = {flat[i] for i in indices if i < len(flat)}
        iids = [iid for iid, obj in self._iid_to_obj.items()
                if obj in selected_polys]
        self._syncing = True
        self._tree.selection_set(iids)
        if iids:
            self._tree.see(iids[-1])
        self._syncing = False

    def _on_select(self, _event):
        if self._syncing:
            return
        sel = self._tree.selection()
        if not sel:
            return

        # Si un groupe est sélectionné, il devient le current_group
        first_obj = self._iid_to_obj.get(sel[0])
        if isinstance(first_obj, Group):
            self._app.current_group = first_obj
            return

        flat    = all_polygons(self._scene.root)
        indices = set()
        for iid in sel:
            obj = self._iid_to_obj.get(iid)
            if not isinstance(obj, Polygon):
                continue
            try:
                indices.add(flat.index(obj))
            except ValueError:
                pass
        if not indices:
            return
        self._scene.selected_indices = indices
        self._scene.selected_idx     = max(indices)

    # ── Renommage inline ──────────────────────────────────────────────────────

    def _on_double_click(self, event):
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        obj = self._iid_to_obj.get(iid)
        if not isinstance(obj, Group) or obj.is_root:
            return
        self._start_rename(iid, obj)

    def _start_rename(self, iid: str, group: Group):
        bbox = self._tree.bbox(iid)
        if not bbox:
            return
        x, y, w, h = bbox
        entry_var = tk.StringVar(value=group.name)
        entry = tk.Entry(
            self._tree,
            textvariable=entry_var,
            bg='#2a2a3a', fg=self._FG,
            insertbackground=self._FG,
            relief='flat', bd=1,
            font=('Segoe UI', 9),
        )
        entry.place(x=x + 18, y=y, width=max(w - 20, 80), height=h)
        entry.focus_set()
        entry.select_range(0, tk.END)

        def commit(_event=None):
            new_name = entry_var.get().strip()
            if new_name:
                group.name = new_name
            entry.destroy()
            self.refresh()

        def cancel(_event=None):
            entry.destroy()

        entry.bind('<Return>',  commit)
        entry.bind('<Escape>',  cancel)
        entry.bind('<FocusOut>', commit)

    def _on_right_click(self, event):
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        obj = self._iid_to_obj.get(iid)
        if not isinstance(obj, Group):
            return

        menu = tk.Menu(self._tree, tearoff=0,
                       bg='#2a2a3a', fg=self._FG,
                       activebackground=self._SEL_BG, activeforeground=self._FG,
                       relief='flat', bd=1)
        menu.add_command(label='Sélectionner tous',
                         command=lambda: self._select_all_in_group(obj))
        menu.tk_popup(event.x_root, event.y_root)

    def _select_all_in_group(self, group: Group):
        flat    = all_polygons(self._scene.root)
        polys   = all_polygons(group)
        indices = {flat.index(p) for p in polys if p in flat}
        if not indices:
            return
        self._scene.selected_indices = indices
        self._scene.selected_idx     = max(indices)
        self.sync_selection(indices)

    def _is_ancestor(self, group: Group, candidate: Group) -> bool:
        node = candidate
        while node is not None:
            if node is group:
                return True
            node = node.parent
        return False
