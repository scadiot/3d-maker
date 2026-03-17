"""Panneau hiérarchique des groupes avec drag & drop."""

import tkinter as tk
from tkinter import ttk

from editor.group import Group, Polygon, all_polygons, is_visible


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
        self._state = getattr(app, 'state', None)
        self._iid_to_obj: dict = {}
        self._drag_iids: list = []
        self._drag_objs: list = []
        self._drop_iid        = None
        self._hover_iid       = None
        self._syncing         = False
        if self._state is not None:
            self._state.subscribe('selection_changed', self._on_selection_changed)
            self._state.subscribe('current_group_changed', self._on_current_group_changed)
            self._state.subscribe('scene_changed', self._on_scene_changed)
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
        self._tree.tag_configure('drop_target', background='#1a3d1a', foreground='#6ddf6d')
        self._tree.tag_configure('hidden', foreground='#555566')

        self._tree.bind('<ButtonPress-1>',   self._on_drag_start)
        self._tree.bind('<B1-Motion>',       self._on_drag_motion)
        self._tree.bind('<ButtonRelease-1>', self._on_drag_end)
        self._tree.bind('<<TreeviewSelect>>', self._on_select)
        self._tree.bind('<Double-ButtonPress-1>', self._on_double_click)
        self._tree.bind('<ButtonPress-3>',   self._on_right_click)
        self._tree.bind('<Delete>',          self._delete_selected)

        self.refresh()

    # ── Rafraîchissement ──────────────────────────────────────────────────────

    def refresh(self):
        """Reconstruit l'arbre depuis scene.root."""
        self._iid_to_obj.clear()
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        self._insert_group(self._scene.root, '')
        self.sync_selection(self._scene.selected_indices)

    def _on_scene_changed(self, change_type: str, **kw):
        """Abonné à StateManager.scene_changed — reconstruit le treeview."""
        self.refresh()

    def _on_selection_changed(self, polygons, edges, vertices, mode):
        """Abonné à StateManager.selection_changed — met à jour le treeview."""
        flat    = all_polygons(self._scene.root)
        idx_map = {id(p): i for i, p in enumerate(flat)}
        indices = {idx_map[id(p)] for p in polygons if id(p) in idx_map}
        self.sync_selection(indices)

    def _on_current_group_changed(self, group: Group):
        """Abonné à StateManager.current_group_changed — met à jour la statusbar."""
        if hasattr(self._app, '_update_statusbar'):
            self._app._update_statusbar()

    def _insert_group(self, group: Group, parent_iid: str):
        if group.is_root:
            text = '⬡ Scène'
        elif group.hidden:
            text = f'▶ {group.name}  [caché]'
        else:
            text = f'▶ {group.name}'
        tags = ('hidden',) if group.hidden else ()
        iid  = self._tree.insert(parent_iid, 'end', text=text, open=True, tags=tags)
        self._iid_to_obj[iid] = group
        for child in group.children:
            self._insert_group(child, iid)
        for poly in group.polygons:
            self._insert_polygon(poly, iid)

    def _insert_polygon(self, poly: Polygon, parent_iid: str):
        flat  = all_polygons(self._scene.root)
        try:
            idx   = flat.index(poly)
            label = f'◆ Polygon {idx}'
        except ValueError:
            label = '◆ Polygon ?'
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
        if self._state is not None:
            new_group = self._state.add_group('Groupe', parent_group)
            history = getattr(self._app, 'history', None)
            if history is not None:
                from editor.history import AddGroupCommand
                history.record(AddGroupCommand(self._state, new_group, parent_group))
        else:
            parent_group.add_group('Groupe')
            self.refresh()

    def _delete_selected(self, *_):
        """Supprime tous les groupes et polygones sélectionnés."""
        sel = self._tree.selection()
        if not sel:
            return

        objs = [self._iid_to_obj[iid] for iid in sel if iid in self._iid_to_obj]
        objs = [o for o in objs if not (isinstance(o, Group) and o.is_root)]
        if not objs:
            return

        # Dédoublonner : si un groupe est sélectionné avec ses enfants,
        # supprimer le groupe suffit (les enfants disparaissent avec lui).
        def is_descendant(obj, ancestors):
            if isinstance(obj, Group):
                node = obj.parent
            else:
                node = obj.group
            while node is not None:
                if node in ancestors:
                    return True
                node = node.parent
            return False

        groups_to_delete = {o for o in objs if isinstance(o, Group)}
        filtered = [o for o in objs if not is_descendant(o, groups_to_delete)]

        groups_to_del = [o for o in filtered if isinstance(o, Group)]
        polys_to_del  = [o for o in filtered if isinstance(o, Polygon)]

        if self._state is not None:
            history = getattr(self._app, 'history', None)
            if history is not None:
                from editor.history import (DeleteGroupCommand, DeletePolygonsCommand,
                                            CompoundCommand)
                cmds = [DeleteGroupCommand(self._state, g) for g in groups_to_del]
                if polys_to_del:
                    saved = [(p, p.group, p.group.polygons.index(p))
                             for p in polys_to_del if p.group is not None]
                    if saved:
                        cmds.append(DeletePolygonsCommand(self._state, saved))
                if cmds:
                    history.push(CompoundCommand(cmds) if len(cmds) > 1 else cmds[0])
            else:
                for g in groups_to_del:
                    self._state.delete_group(g)
                if polys_to_del:
                    self._state.delete_polygons(polys_to_del)
        else:
            for obj in filtered:
                if isinstance(obj, Group):
                    if obj.parent is not None:
                        obj.parent.remove_group(obj)
                else:
                    if obj.group is not None:
                        obj.group.remove_polygon(obj)
            self.refresh()
        return 'break'

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
        # Empêche le Treeview de modifier la sélection pendant le déplacement
        self._syncing = True
        self._tree.selection_set(self._drag_iids)
        self._syncing = False

        # Surbrillance verte du groupe cible survolé
        hovered_iid = self._tree.identify_row(event.y)
        new_hover_iid = None
        if hovered_iid and hovered_iid not in self._drag_iids:
            obj = self._iid_to_obj.get(hovered_iid)
            if obj is not None:
                target_group = obj if isinstance(obj, Group) else (obj.group or self._scene.root)
                new_hover_iid = next(
                    (i for i, o in self._iid_to_obj.items() if o is target_group), None
                )
        if new_hover_iid != self._hover_iid:
            if self._hover_iid:
                self._tree.item(self._hover_iid, tags=())
            self._hover_iid = new_hover_iid
            if new_hover_iid:
                self._tree.item(new_hover_iid, tags=('drop_target',))

        return 'break'

    def _on_drag_end(self, event):
        self._tree.config(cursor='')
        if self._hover_iid:
            self._tree.item(self._hover_iid, tags=())
            self._hover_iid = None
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

        moved = False
        history = getattr(self._app, 'history', None)
        move_cmds = []
        for drag_obj in drag_objs:
            if isinstance(drag_obj, Group):
                # Anti-cycle : pas de déplacement dans soi-même ou ses descendants
                if drag_obj is target_group or self._is_ancestor(drag_obj, target_group):
                    continue
                if drag_obj.parent is target_group:
                    continue
                if self._state is not None:
                    if history is not None:
                        from editor.history import MoveGroupCommand
                        old_parent = drag_obj.parent
                        move_cmds.append(MoveGroupCommand(self._state, drag_obj,
                                                          old_parent, target_group))
                    else:
                        self._state.move_group(drag_obj, target_group)
                else:
                    target_group.adopt_group(drag_obj)
                moved = True
            else:
                if drag_obj.group is target_group:
                    continue
                if self._state is not None:
                    if history is not None:
                        from editor.history import MovePolygonCommand
                        old_group = drag_obj.group
                        move_cmds.append(MovePolygonCommand(self._state, drag_obj,
                                                            old_group, target_group))
                    else:
                        self._state.move_polygon(drag_obj, target_group)
                else:
                    target_group.adopt_polygon(drag_obj)
                moved = True

        if move_cmds:
            from editor.history import CompoundCommand
            history.push(CompoundCommand(move_cmds) if len(move_cmds) > 1 else move_cmds[0])
        elif moved and self._state is None:
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
            if self._state is not None:
                self._state.set_current_group(first_obj)
            else:
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
            entry.destroy()
            if new_name and new_name != group.name:
                if self._state is not None:
                    old_name = group.name
                    history = getattr(self._app, 'history', None)
                    if history is not None:
                        from editor.history import RenameGroupCommand
                        history.push(RenameGroupCommand(self._state, group,
                                                        old_name, new_name))
                    else:
                        self._state.rename_group(group, new_name)
                else:
                    group.name = new_name
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

        # Si l'item cliqué n'est pas dans la sélection, le sélectionner seul
        sel = list(self._tree.selection())
        if iid not in sel:
            self._tree.selection_set([iid])
            sel = [iid]

        clicked_obj = self._iid_to_obj.get(iid)
        objs    = [self._iid_to_obj[i] for i in sel if i in self._iid_to_obj]
        movable = [o for o in objs if not (isinstance(o, Group) and o.is_root)]

        menu = tk.Menu(self._tree, tearoff=0,
                       bg='#2a2a3a', fg=self._FG,
                       activebackground=self._SEL_BG, activeforeground=self._FG,
                       relief='flat', bd=1)
        has_items = False

        if isinstance(clicked_obj, Group) and not clicked_obj.is_root:
            menu.add_command(label='Sélectionner tous',
                             command=lambda: self._select_all_in_group(clicked_obj))
            menu.add_separator()
            menu.add_command(label='Cacher',
                             command=lambda: self._set_group_hidden(clicked_obj, True))
            menu.add_command(label='Afficher',
                             command=lambda: self._set_group_hidden(clicked_obj, False))
            has_items = True

        if movable:
            if has_items:
                menu.add_separator()
            menu.add_command(label='Déplacer dans un groupe',
                             command=lambda: self._show_move_to_group_dialog(movable))
            has_items = True

        if not has_items:
            return
        menu.tk_popup(event.x_root, event.y_root)

    def _show_move_to_group_dialog(self, movable: list):
        """Affiche la popup de sélection du groupe cible."""
        selected_groups = {o for o in movable if isinstance(o, Group)}

        def is_excluded(group: Group) -> bool:
            """Exclut les groupes sélectionnés et leurs descendants."""
            if group in selected_groups:
                return True
            node = group.parent
            while node is not None:
                if node in selected_groups:
                    return True
                node = node.parent
            return False

        def collect_groups(node: Group) -> list:
            if is_excluded(node):
                return []
            result = [node]
            for child in node.children:
                result.extend(collect_groups(child))
            return result

        valid_groups = collect_groups(self._scene.root)
        if not valid_groups:
            return

        def group_label(group: Group) -> str:
            depth = 0
            node = group.parent
            while node is not None:
                depth += 1
                node = node.parent
            prefix = '  ' * depth
            return prefix + ('Scène' if group.is_root else group.name)

        labels = [group_label(g) for g in valid_groups]

        popup = tk.Toplevel(self._tree)
        popup.title('Déplacer dans un groupe')
        popup.configure(bg='#1a1a21')
        popup.resizable(False, False)
        popup.transient(self._tree.winfo_toplevel())
        popup.grab_set()

        popup.update_idletasks()
        w, h = 300, 130
        x = self._tree.winfo_rootx() + self._tree.winfo_width() // 2 - w // 2
        y = self._tree.winfo_rooty() + self._tree.winfo_height() // 2 - h // 2
        popup.geometry(f'{w}x{h}+{x}+{y}')

        tk.Label(popup, text='Groupe cible :',
                 bg='#1a1a21', fg=self._FG,
                 font=('Segoe UI', 9)).pack(padx=12, pady=(12, 4), anchor='w')

        combo_var = tk.StringVar(value=labels[0])
        combo = ttk.Combobox(popup, textvariable=combo_var, values=labels,
                             state='readonly', font=('Segoe UI', 9))
        combo.pack(fill=tk.X, padx=12, pady=4)

        btn_frame = tk.Frame(popup, bg='#1a1a21')
        btn_frame.pack(pady=8)

        def on_ok(_event=None):
            idx = combo.current()
            if idx < 0:
                return
            self._do_move_to_group(movable, valid_groups[idx])
            popup.destroy()

        tk.Button(btn_frame, text='OK', command=on_ok,
                  bg='#2d4080', fg=self._FG,
                  activebackground='#3d50a0', activeforeground=self._FG,
                  relief='flat', bd=0, font=('Segoe UI', 9), width=8,
                  cursor='hand2').pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text='Annuler', command=popup.destroy,
                  bg='#2a2a3a', fg=self._FG,
                  activebackground='#3a3a4a', activeforeground=self._FG,
                  relief='flat', bd=0, font=('Segoe UI', 9), width=8,
                  cursor='hand2').pack(side=tk.LEFT, padx=4)

        popup.bind('<Return>', on_ok)
        popup.bind('<Escape>', lambda _: popup.destroy())

    def _do_move_to_group(self, movable: list, target_group: Group):
        """Déplace les éléments sélectionnés vers target_group (avec undo/redo)."""
        history    = getattr(self._app, 'history', None)
        move_cmds  = []

        for obj in movable:
            if isinstance(obj, Group):
                if obj is target_group or self._is_ancestor(obj, target_group):
                    continue
                if obj.parent is target_group:
                    continue
                if self._state is not None and history is not None:
                    from editor.history import MoveGroupCommand
                    move_cmds.append(MoveGroupCommand(self._state, obj,
                                                      obj.parent, target_group))
                elif self._state is not None:
                    self._state.move_group(obj, target_group)
                else:
                    target_group.adopt_group(obj)
            else:
                if obj.group is target_group:
                    continue
                if self._state is not None and history is not None:
                    from editor.history import MovePolygonCommand
                    move_cmds.append(MovePolygonCommand(self._state, obj,
                                                        obj.group, target_group))
                elif self._state is not None:
                    self._state.move_polygon(obj, target_group)
                else:
                    target_group.adopt_polygon(obj)

        if move_cmds:
            from editor.history import CompoundCommand
            history.push(CompoundCommand(move_cmds) if len(move_cmds) > 1 else move_cmds[0])
        elif self._state is None:
            self.refresh()

    def _select_all_in_group(self, group: Group):
        flat    = all_polygons(self._scene.root)
        polys   = all_polygons(group)
        indices = {flat.index(p) for p in polys if p in flat}
        if not indices:
            return
        self._scene.selected_indices = indices  # → StateManager → selection_changed → sync_selection()

    def _set_group_hidden(self, group: Group, hidden: bool):
        """Cache ou affiche un groupe et rafraîchit l'affichage."""
        group.hidden = hidden
        self.refresh()
        if self._state is not None:
            self._state.notify('scene_changed', change_type='visibility')

    def _is_ancestor(self, group: Group, candidate: Group) -> bool:
        node = candidate
        while node is not None:
            if node is group:
                return True
            node = node.parent
        return False
