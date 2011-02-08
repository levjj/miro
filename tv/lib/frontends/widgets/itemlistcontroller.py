# Miro - an RSS based video player application
# Copyright (C) 2005, 2006, 2007, 2008, 2009, 2010, 2011
# Participatory Culture Foundation
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
#
# In addition, as a special exception, the copyright holders give
# permission to link the code of portions of this program with the OpenSSL
# library.
#
# You must obey the GNU General Public License in all respects for all of
# the code used other than OpenSSL. If you modify file(s) with this
# exception, you may extend this exception to your version of the file(s),
# but you are not obligated to do so. If you do not wish to do so, delete
# this exception statement from your version. If you delete this exception
# statement from all source files in the program, then also delete it here.

"""itemlistcontroller.py -- Controllers for item lists.

itemlist, itemlistcontroller and itemlistwidgets work together using
the MVC pattern.  itemlist handles the Model, itemlistwidgets handles
the View and itemlistcontroller handles the Controller.

This module contains the ItemListController base class along with
controllers that work for the static tabs which are pretty simple
cases.
"""

import logging
import os
from urlparse import urljoin

from miro import app
from miro import messages
from miro import subscription
from miro import prefs
from miro.gtcache import gettext as _
from miro.frontends.widgets import dialogs
from miro.frontends.widgets import itemcontextmenu
from miro.frontends.widgets import itemlist
from miro.frontends.widgets import itemtrack
from miro.frontends.widgets import itemlistwidgets
from miro.frontends.widgets import imagepool
from miro.frontends.widgets import widgetutil
from miro.frontends.widgets import separator
from miro.frontends.widgets import menus
from miro.frontends.widgets.widgetstatestore import WidgetStateStore
from miro.plat.frontends.widgets import widgetset
from miro.plat import resources

class ItemListDragHandler(object):
    def allowed_actions(self):
        return widgetset.DRAG_ACTION_COPY | widgetset.DRAG_ACTION_MOVE

    def allowed_types(self):
        return ('downloaded-item',)

    def begin_drag(self, tableview, rows):
        videos = []
        for row in rows:
            item_info = row[0]
            if item_info.downloaded:
                videos.append(item_info)
        if videos:
            data = '-'.join(str(info.id) for info in videos)
            return {'downloaded-item':  data }
        else:
            return None

class FilteredListMixin(object):
    """Track a filter switch attached to an ItemListController
    """
    def __init__(self):
        filters = app.widget_state.get_filters(self.type, self.id)
        self.update_filters(filters)

    def on_toggle_filter(self, button, filter_):
        """Handle the filter switch changing state."""
        self.update_filters(filter_)
        app.widget_state.toggle_filters(self.type, self.id, filter_)

    def update_filters(self, filters):
        """Update the display and toolbar filter switch state."""
        self.widget.toggle_filter(filters)
        self.item_list.toggle_filter(filters)
        for item_view in self.views.values():
            item_view.model_changed()
        self.check_for_empty_list()

class ItemListController(object):
    """Base class for controllers that manage list of items.
    
    :attribute widget: Container widget used to display this controller
    :attribute views: The ListView and StandardView objects
    """
    def __init__(self, typ, id_):
        """Construct a ItemListController.

        type and id are the same as in the constructor to
        messages.TrackItems
        """
        self.type = typ
        self.id = id_
        self.views = {}
        self._search_text = ''
        self.item_tracker = None
        self._init_widget()

        item_lists = set(iv.item_list for iv in self.views.values())
        self.item_list_group = itemlist.ItemListGroup(item_lists)
        self.multiview_sorter = None
        self.make_multiview_sorters()
        self.make_sorters()
        self._init_item_views()
        self.initialize_search()
        self._items_added_callback = self._playback_item_list = None
        self._item_tracker_callbacks = []
        self._playback_callbacks = []

    def make_multiview_sorters(self):
        """Subclasses that need to share one sorter across all views can set
        self.multiview_sorter here. PlaylistView uses this.
        """
        pass
    
    def make_sorters(self):
        for view_type, view in self.views.items():
            if self.multiview_sorter is None:
                sorter = self.get_sorter(view_type)
            else:
                sorter = self.multview_sorter
            view.item_list.set_sort(sorter)
            if WidgetStateStore.is_list_view(view_type):
                view.change_sort_indicator(sorter.KEY, sorter.is_ascending())
            else:
                self.widget.toolbar.change_sort_indicator(
                        sorter.KEY, sorter.is_ascending())

    def get_sorter(self, view_type):
        sort_key = app.widget_state.get_sort_state(
                self.type, self.id, view_type)
        return self.make_sorter(sort_key)

    def make_sorter(self, key):
        if key.startswith('-'):
            column = key[1:]
            ascending = False
        else:
            column = key
            ascending = True
        return itemlist.SORT_KEY_MAP[column](ascending)

    def make_sort_key(self, sorter):
        key = unicode(sorter.KEY)
        if sorter.is_ascending():
            state = key
        else:
            state = u'-' + key
        return state

    def _init_widget(self):
        toolbar = self.build_header_toolbar()
        self.selected_view = app.widget_state.get_selected_view(self.type, self.id)
        self.widget = itemlistwidgets.ItemContainerWidget(toolbar,
                self.selected_view)
        self.item_list = itemlist.ItemList()

        self.build_widget()

        list_view = WidgetStateStore.get_list_view_type()
        self.views[list_view] = self.build_list_view()

        standard_view = WidgetStateStore.get_standard_view_type()
        self.views[standard_view] = self.build_standard_view()

        toolbar.connect_weak('sort-changed',
            self.on_sort_changed, standard_view)
        self.views[list_view].connect_weak('sort-changed',
            self.on_sort_changed, list_view)
        toolbar.connect_weak('list-view-clicked',
            self.set_view, list_view)
        toolbar.connect_weak('normal-view-clicked',
            self.set_view, standard_view)
        self.views[list_view].connect_weak('columns-enabled-changed',
            self.on_columns_enabled_changed, list_view)
        self.views[list_view].connect_weak('column-widths-changed',
            self.on_column_widths_changed, list_view)

    def set_view(self, _widget, view):
        self.selected_view = view
        self.widget.switch_to_view(view)
        app.widget_state.set_selected_view(self.type, self.id, self.selected_view)
        app.menu_manager.update_menus()

    def get_current_item_view(self):
        return self.views[self.selected_view]
    current_item_view = property(get_current_item_view)

    def build_widget(self):
        """Build the container widget for this controller."""
        raise NotImplementedError()

    def build_standard_view(self):
        """Build the standard view widget for this controller."""
        raise NotImplementedError()

    def build_list_view(self):
        """Build the list view widget for this controller."""
        list_view_type = WidgetStateStore.get_list_view_type()
        list_view_columns = app.widget_state.get_columns_enabled(
                self.type, self.id, list_view_type)
        list_view_widths = app.widget_state.get_column_widths(
                self.type, self.id, list_view_type)
        list_view = itemlistwidgets.ListView(
               self.item_list, list_view_columns, list_view_widths)
        scroller = widgetset.Scroller(True, True)
        scroller.add(list_view)
        self.widget.vbox[list_view_type].pack_start(scroller, expand=True)
        return list_view

    def build_header_toolbar(self):
        return itemlistwidgets.HeaderToolbar()

    def update_columns_enabled(self):
        list_view = WidgetStateStore.get_list_view_type()
        list_view_columns = app.widget_state.get_columns_enabled(
                self.type, self.id, list_view)
        list_view_widths = app.widget_state.get_column_widths(
                self.type, self.id, list_view)
        self.views[list_view].update_columns(list_view_columns,
            list_view_widths)

    def _init_item_views(self):
        self.context_menu_handler = self.make_context_menu_handler()
        context_callback = self.context_menu_handler.callback
        for item_view in self.views.values():
            item_view.connect_weak('selection-changed',
                    self.on_selection_changed)
            item_view.connect_weak('hotspot-clicked', self.on_hotspot_clicked)
            item_view.connect_weak('key-press', self.on_key_press)
            item_view.connect_weak('row-double-clicked',
                    self.on_row_double_clicked)
            item_view.connect_weak('row-activated', self.on_row_activated)
            item_view.set_context_menu_callback(context_callback)
            item_view.set_drag_source(self.make_drag_handler())
            item_view.set_drag_dest(self.make_drop_handler())

    def initialize_search(self):
        search = app.inline_search_memory.get_search(self.type, self.id)
        if search != '':
            self.titlebar.set_search_text(search)
            self.set_search(search)

    def get_selection(self):
        """Get the currently selected items.  Returns a list of
        ItemInfos.
        """
        item_view = self.current_item_view
        return [item_view.model[i][0] for i in item_view.get_selection()]

    def play_selection(self, presentation_mode='fit-to-bounds'):
        """Play the currently selected items."""
        selection = self.get_selection()
        if len(selection) == 0:
            start_id = None
        elif len(selection) == 1:
            start_id = selection[0].id
        else:
            selected_ids = [i.id for i in selection]
            selected_ids.sort(key=self.item_list.model.index_of_id)
            start_id = selected_ids[0]
        self._play_item_list(start_id, presentation_mode)

    def can_play_items(self):
        for info in self.item_list.model.info_list():
            if info.is_playable:
                return True
        return False

    def _play_item_list(self, start_id, presentation_mode='fit-to-bounds'):
        if start_id is None and not self.can_play_items():
            return
        elif (start_id is not None and not
                self.item_list.model.get_info(start_id).is_playable):
            logging.warn("_play_item_list called with unplayable item")
            return
        app.playback_manager.stop()
        if ((app.config.get(prefs.PLAY_IN_MIRO)
             and len(self.get_selection()) <= 1)):
            if self._items_added_callback is not None:
                self._playback_item_list.disconnect(self._items_added_callback)
            # User is playing items in Miro and has 0 or 1 items
            # selected, if more items get added to the item list, we
            # should play them.
            item_list = self.current_item_view.item_list
            self._playback_item_list = item_list
        app.playback_manager.start(start_id, self.item_tracker,
                presentation_mode)

    def set_search(self, search_text):
        """Set the search for all ItemViews managed by this controller.
        """
        self._search_text = search_text
        if self.item_tracker:
            self.item_tracker.set_search(search_text)
        app.inline_search_memory.set_search(self.type, self.id, search_text)

    def _trigger_item(self, item_view, info):
        if info.downloaded:
            items = item_view.item_list.get_items(start_id=info.id)
            self._play_item_list(info.id)
        elif info.state == 'downloading':
            messages.PauseDownload(info.id).send_to_backend()
        elif info.state == 'paused':
            messages.ResumeDownload(info.id).send_to_backend()
        elif info.download_info is None:
            messages.StartDownload(info.id).send_to_backend()


    def on_row_double_clicked(self, item_view, iter_):
        info = item_view.model[iter_][0]
        self._trigger_item(item_view, info)

    def on_row_activated(self, item_view, iter_):
        info = item_view.model[iter_][0]
        if app.playback_manager.is_playing_id(info.id):
            app.playback_manager.play_pause()
        else:
            self._trigger_item(item_view, info)

    def on_sort_changed(self, object, sort_key, ascending, view):
        self.views[view].start_bulk_change()
        sorter = itemlist.SORT_KEY_MAP[sort_key](ascending)
        self.views[view].item_list.set_sort(sorter)
        self.views[view].model_changed()
        list_view = WidgetStateStore.get_list_view_type()
        if view == list_view:
            self.views[list_view].change_sort_indicator(sort_key, ascending)
        else:
            self.widget.toolbar.change_sort_indicator(sort_key, ascending)
        sort_key = self.make_sort_key(sorter)
        app.widget_state.set_sort_state(self.type, self.id, view, sort_key)

    def on_columns_enabled_changed(self, object, columns, view_type):
        app.widget_state.set_columns_enabled(
                self.type, self.id, view_type, columns)

    def on_column_widths_changed(self, object, widths, view_type):
        app.widget_state.update_column_widths(
                self.type, self.id, view_type, widths)

    def on_key_press(self, view, key, mods):
        if key == menus.DELETE:
            return self.handle_delete()

    def handle_delete(self):
        app.widgetapp.remove_items(self.get_selection())
        return True

    def on_hotspot_clicked(self, itemview, name, iter_):
        """Hotspot handler for ItemViews."""

        item_info, attrs = itemview.model[iter_]
        if name in ('download', 'thumbnail-download'):
            messages.StartDownload(item_info.id).send_to_backend()
        elif name == 'pause':
            messages.PauseDownload(item_info.id).send_to_backend()
        elif name == 'resume':
            messages.ResumeDownload(item_info.id).send_to_backend()
        elif name == 'cancel':
            messages.CancelDownload(item_info.id).send_to_backend()
        elif name == 'keep':
            messages.KeepVideo(item_info.id).send_to_backend()
        elif name == 'stop_seeding':
            messages.StopUpload(item_info.id).send_to_backend()
        elif name == 'start_seeding':
            messages.StartUpload(item_info.id).send_to_backend()
        elif name == 'delete':
            app.widgetapp.remove_items(selection=[item_info])
        elif name == 'remove':
            messages.RemoveVideosFromPlaylist(
                itemview.playlist_id, [item_info.id]).send_to_backend()
        elif name == 'visit_webpage':
            app.widgetapp.open_url(item_info.permalink)
        elif name == 'visit_comments':
            app.widgetapp.open_url(item_info.commentslink)
        elif name == 'visit_filelink':
            app.widgetapp.open_url(item_info.file_url)
        elif name == 'visit_license':
            app.widgetapp.open_url(item_info.license)
        elif name == 'show_local_file':
            app.widgetapp.check_then_reveal_file(item_info.video_path)
        elif name == 'show_contents':
            app.display_manager.push_folder_contents_display(item_info)
        elif name == 'cancel_auto_download':
            messages.CancelAutoDownload(item_info.id).send_to_backend()
        elif name.startswith('description-link:'):
            url = name.split(':', 1)[1]
            try:
                base_href = widgetutil.get_feed_info(item_info.feed_id).base_href
            except KeyError:
                logging.warn("Feed not present when clicking link (%s)",
                        item_info.feed_id)
                # Feed is not around anymore for some reason (#13310).
                # Try without base_href
            else:
                url = urljoin(base_href, url)
            if subscription.is_subscribe_link(url):
                messages.SubscriptionLinkClicked(url).send_to_backend()
            else:
                app.widgetapp.open_url(url)
        elif name in ('play', 'thumbnail-play'):
            self._play_item_list(item_info.id)
        elif name == 'play_pause':
            app.playback_manager.play_pause()
        elif name.startswith('rate:'):
            rating = int(name.split(':', 1)[1])
            messages.RateItem(item_info, rating).send_to_backend()
        else:
            logging.debug("ItemView doesn't know how to handle hotspot %s.",
                name)

    def on_selection_changed(self, item_view):
        app.menu_manager.update_menus()

    def start_tracking(self):
        """Send the message to start tracking items."""
        self.track_item_lists(self.type, self.id)
        self.track_playback()

    def stop_tracking(self):
        """Send the message to stop tracking items."""
        self.cancel_track_item_lists()
        self.cancel_track_playback()

    def track_item_lists(self, type_, id_):
        if self.item_tracker is not None:
            raise AssertionError("called track_item_lists() twice")
        # FIXME: we're not really using multiple items anymore, hence the
        # following hack.  We should remove ItemListGroup though
        if len(self.item_list_group.item_lists) != 1:
            raise AssertionError("wrong number of item lists: %s",
                    len(self.item_list_group.item_lists))
        item_list = list(self.item_list_group.item_lists)[0]
        item_tracker = itemtrack.ItemListTracker(type_, id_, item_list)
        item_tracker.set_search(self._search_text)
        self._item_tracker_callbacks = [
            item_tracker.connect("initial-list", self.handle_item_list),
            item_tracker.connect("items-changed", self.handle_items_changed),
        ]
        self.item_tracker = item_tracker

    def cancel_track_item_lists(self):
        if self.item_tracker is None:
            return # never started tracking
        for handle in self._item_tracker_callbacks:
            self.item_tracker.disconnect(handle)
        self.item_tracker = None
        self._item_tracker_callbacks = []

    def track_playback(self):
        self._playback_callbacks.extend([
            app.playback_manager.connect('selecting-file',
                self._on_playback_change),
            app.playback_manager.connect('will-stop',
                self._playback_will_stop),
        ])

    def cancel_track_playback(self):
        for handle in self._playback_callbacks:
            app.playback_manager.disconnect(handle)
        self._playback_callbacks = []

    def _on_playback_change(self, playback_manager, *args):
        # The currently playing item has changed, redraw the view to
        # change which item gets the "currently playing" badge.
        for item_view in self.views.values():
            item_view.queue_redraw()

    def _playback_will_stop(self, playback_manager):
        self._on_playback_change(playback_manager)
        if self._items_added_callback is not None:
            self._playback_item_list.disconnect(self._items_added_callback)
            self._playback_item_list = self._items_added_callback = None

    def handle_item_list(self, obj, items):
        """Handle an ItemList message meant for this ItemContainer."""
        for item_view in self.views.values():
            item_view.model_changed()
        self.on_initial_list()

    def handle_items_changed(self, obj, added, changed, removed):
        """Handle an ItemsChanged message meant for this ItemContainer."""
        for item_view in self.views.values():
            item_view.model_changed()
        self.on_items_changed()

    def on_initial_list(self):
        """Called after we have receieved the initial list of items.

        Subclasses can override this method if they want.
        """
        pass

    def on_items_changed(self):
        """Called after we have changes to items

        Subclasses can override this method if they want.
        """
        pass

    def make_context_menu_handler(self):
        return itemcontextmenu.ItemContextMenuHandler()

    def make_drag_handler(self):
        return ItemListDragHandler()

    def make_drop_handler(self):
        return None

    def no_longer_displayed(self):
        list_view = WidgetStateStore.get_list_view_type()
        if list_view in self.views:
            self.views[list_view].on_undisplay()

class SimpleItemListController(ItemListController):
    def __init__(self):
        self.display_channel = True
        ItemListController.__init__(self, self.type, self.id)

    def build_widget(self):
        self.titlebar = self.make_titlebar()
        self.widget.titlebar_vbox.pack_start(self.titlebar)

    def build_standard_view(self):
        scroller = widgetset.Scroller(False, True)
        standard_view_type = WidgetStateStore.get_standard_view_type()
        standard_view = self.get_standard_view()
        scroller.add(standard_view)
        self.widget.vbox[standard_view_type].pack_start(scroller, expand=True)
        return standard_view

    def get_standard_view(self):
        return itemlistwidgets.StandardView(self.item_list, self.display_channel)

    def make_titlebar(self):
        icon = self._make_icon()
        titlebar = itemlistwidgets.ItemListTitlebar(self.title, icon)
        titlebar.connect('search-changed', self._on_search_changed)
        return titlebar

    def _on_search_changed(self, widget, search_text):
        self.set_search(search_text)
        self.check_for_empty_list()

    def _make_icon(self):
        image_path = resources.path("images/%s" % self.image_filename)
        return imagepool.get(image_path)

    def on_initial_list(self):
        self.check_for_empty_list()

    def on_items_changed(self):
        self.check_for_empty_list()

    def check_for_empty_list(self):
        list_empty = (self.item_list.get_count() == 0)
        self.widget.set_list_empty_mode(list_empty)

class SearchController(SimpleItemListController):
    type = u'search'
    id = u'search'
    image_filename = 'icon-search_large.png'
    title = _("Video Search")

    def __init__(self):
        SimpleItemListController.__init__(self)
        self.toolbar = itemlistwidgets.SearchToolbar()
        self.toolbar.connect("save-search", self._on_save_search)
        if app.search_manager.text != '':
            self.toolbar.show()
        sep = separator.HSeparator((0.85, 0.85, 0.85), (0.95, 0.95, 0.95))
        self.widget.titlebar_vbox.pack_start(sep)
        self.widget.titlebar_vbox.pack_start(self.toolbar)

    def build_widget(self):
        SimpleItemListController.build_widget(self)
        text = _('No Results')
        self.widget.list_empty_mode_vbox.pack_start(
                itemlistwidgets.EmptyListHeader(text))

        text = _('To search for media on Internet media search sites, click '
                 'on the search box above, type in search terms and hit '
                 'the Enter key.  To switch search engines, click on the '
                 'icon to the left of the search box above and select the '
                 'search engine from the drop down.')
        self.widget.list_empty_mode_vbox.pack_start(
                itemlistwidgets.EmptyListDescription(text))


    def initialize_search(self):
        if app.search_manager.text != '':
            self.titlebar.set_search_text(app.search_manager.text)
        self.titlebar.set_search_engine(app.search_manager.engine)

    def on_initial_list(self):
        if ((not app.search_manager.searching
             and self.item_list.get_count() == 0)):
            self.widget.set_list_empty_mode(True)

    def on_items_changed(self):
        # Don't check for an empty list here.  Since items don't get
        # removed from the search feed, we don't need to do anything.
        # Also, it results in a false positive just after the search
        # starts when the items from the last search get removed
        # (#11255)
        pass

    def make_titlebar(self):
        icon = self._make_icon()
        titlebar = itemlistwidgets.SearchListTitlebar(self.title, icon)
        return titlebar

    def _on_save_search(self, widget):
        engine = self.titlebar.get_engine()
        search_text = self.titlebar.get_text()
        app.search_manager.perform_search(engine, search_text)
        if search_text != '':
            app.search_manager.save_search()

    def start_tracking(self):
        SimpleItemListController.start_tracking(self)
        self._started_handle = app.search_manager.connect('search-started',
                self._on_search_started)
        self._complete_handle = app.search_manager.connect('search-complete',
                self._on_search_complete)

    def stop_tracking(self):
        SimpleItemListController.stop_tracking(self)
        app.search_manager.disconnect(self._started_handle)
        app.search_manager.disconnect(self._complete_handle)

    def _on_search_started(self, search_manager):
        self.titlebar.set_search_text(search_manager.text)
        self.titlebar.set_search_engine(search_manager.engine)
        self.widget.set_list_empty_mode(False)
        if search_manager.text != '':
            self.toolbar.show()
        else:
            self.toolbar.hide()

    def _on_search_complete(self, search_manager, result_count):
        if search_manager.text != '' and result_count == 0:
            self.widget.set_list_empty_mode(True)

class AudioVideoItemsController(SimpleItemListController, FilteredListMixin):
    def __init__(self):
        SimpleItemListController.__init__(self)
        FilteredListMixin.__init__(self)

    def build_header_toolbar(self):
        toolbar = itemlistwidgets.LibraryHeaderToolbar(self.unwatched_label)
        toolbar.connect_weak('toggle-filter', self.on_toggle_filter)
        return toolbar

class VideoItemsController(AudioVideoItemsController):
    type = u'videos'
    id = u'videos'
    image_filename = 'icon-video_large.png'
    title = _("Video")
    unwatched_label =  _('Unwatched')
    display_channel = True

class AudioItemsController(AudioVideoItemsController):
    type = u'music'
    id = u'music'
    image_filename = 'icon-audio_large.png'
    title = _("Music")
    unwatched_label = _('Unplayed')
    display_channel = True

class OtherItemsController(SimpleItemListController):
    type = u'others'
    id = u'others'
    image_filename = 'icon-other_large.png'
    title = _("Other")
    display_channel = True

class FolderContentsController(SimpleItemListController):
    """Controller object for feeds."""

    def __init__(self, folder_info):
        self.type = u'folder-contents'
        self.id = folder_info.id
        self.title = folder_info.name
        self.info = folder_info
        SimpleItemListController.__init__(self)

    def _make_icon(self):
        return imagepool.get(resources.path('images/folder-icon.png'))

    def build_widget(self):
        SimpleItemListController.build_widget(self)

        button = widgetset.Button(_('Back to podcast'))
        button.connect('clicked', self._on_clicked)
        self.widget.titlebar_vbox.pack_start(widgetutil.align_left(button,
            left_pad=10, top_pad=6, bottom_pad=4))

    def _on_clicked(self, button):
        app.display_manager.pop_display()

class ItemListControllerManager(object):
    """Manages ItemListController objects.

    Attributes:

    :attribute displayed: Currently displayed ItemListController or
        None (this one is currently being displayed in the right-hand
        side)
    :attribute all_controllers: Set of all ItemListControllers in use
        (these are somewhere in the display stack, but not necessarily
        displayed currently).
    """

    def __init__(self):
        self.displayed = None
        self.all_controllers = set()

    def controller_displayed(self, item_list_controller):
        self.displayed = item_list_controller

    def controller_no_longer_displayed(self, item_list_controller):
        if item_list_controller is not self.displayed:
            logging.warn("controller is not displayed in "
                    "controller_no_longer_displayed()")
        else:
            self.displayed.no_longer_displayed()
        self.displayed = None

    def controller_created(self, item_list_controller):
        self.all_controllers.add(item_list_controller)

    def controller_destroyed(self, item_list_controller):
        self.all_controllers.remove(item_list_controller)

    def play_selection(self, presentation_mode='fit-to-bounds'):
        if self.displayed is not None:
            self.displayed.play_selection(presentation_mode)

    def get_selection(self):
        if self.displayed is None:
            return []
        else:
            return self.displayed.get_selection()

    def can_play_items(self):
        """Can we play any items currently?"""
        return self.displayed and self.displayed.can_play_items()

    def undisplay_controller(self):
        if self.displayed:
            self.controller_no_longer_displayed(self.displayed)
