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

"""miro.plat.frontends.widgets.control - Controls."""

from AppKit import *
from Foundation import *
from objc import YES, NO, nil

import os

from miro.frontends.widgets import widgetconst
from miro.plat import resources
from miro.plat.frontends.widgets import wrappermap
from miro.plat.frontends.widgets.base import Widget
from miro.plat.frontends.widgets.helpers import NotificationForwarder

from miro import searchengines
from miro import app
from miro import prefs

class SizedControl(Widget):
    def set_size(self, size):
        if size == widgetconst.SIZE_NORMAL:
            self.view.cell().setControlSize_(NSRegularControlSize)
            font = NSFont.systemFontOfSize_(NSFont.systemFontSize())
        elif size == widgetconst.SIZE_SMALL:
            font = NSFont.systemFontOfSize_(NSFont.smallSystemFontSize())
            self.view.cell().setControlSize_(NSSmallControlSize)
        else:
            self.view.cell().setControlSize_(NSRegularControlSize)
            font = NSFont.systemFontOfSize_(NSFont.systemFontSize() * size)
        self.view.setFont_(font)

class BaseTextEntry(SizedControl):
    """See https://develop.participatoryculture.org/index.php/WidgetAPI for a description of the API for this class."""
    def __init__(self, initial_text=None):
        SizedControl.__init__(self)
        self.view = self.make_view()
        self.font = NSFont.systemFontOfSize_(NSFont.systemFontSize())
        self.view.setFont_(self.font)
        self.view.setEditable_(YES)
        self.view.cell().setScrollable_(YES)
        self.view.cell().setLineBreakMode_(NSLineBreakByClipping)
        self.sizer_cell = self.view.cell().copy()
        if initial_text:
            self.view.setStringValue_(initial_text)
            self.set_width(len(initial_text))
        else:
            self.set_width(10)

        self.notifications = NotificationForwarder.create(self.view)

        self.create_signal('activate')
        self.create_signal('changed')
        self.create_signal('validate')

    def focus(self):
        if self.view.window() is not None:
            self.view.window().makeFirstResponder_(self.view)

    def start_editing(self, initial_text):
        self.set_text(initial_text)
        self.focus()
        # unselect the text and locate the cursor at the end of the entry
        text_field = self.view.window().fieldEditor_forObject_(YES, self.view)
        text_field.setSelectedRange_(NSMakeRange(len(self.get_text()), 0))

    def viewport_created(self):
        SizedControl.viewport_created(self)
        self.notifications.connect(self.on_changed, 'NSControlTextDidChangeNotification')
        self.notifications.connect(self.on_end_editing,
                'NSControlTextDidEndEditingNotification')

    def remove_viewport(self):
        SizedControl.remove_viewport(self)
        self.notifications.disconnect()

    def baseline(self):
        return -self.view.font().descender() + 2

    def on_changed(self, notification):
        self.emit('changed')

    def on_end_editing(self, notification):
        self.emit('focus-out')

    def calc_size_request(self):
        size = self.sizer_cell.cellSize()
        return size.width, size.height

    def set_text(self, text):
        self.view.setStringValue_(text)
        self.emit('changed')

    def get_text(self):
        return self.view.stringValue()

    def set_width(self, chars):
        self.sizer_cell.setStringValue_('X' * chars)
        self.invalidate_size_request()

    def set_activates_default(self, setting):
        pass

    def enable(self):
        SizedControl.enable(self)
        self.view.setEnabled_(True)

    def disable(self):
        SizedControl.disable(self)
        self.view.setEnabled_(False)

class MiroTextField(NSTextField):
    def textDidEndEditing_(self, notification):
        wrappermap.wrapper(self).emit('activate')
        return NSTextField.textDidEndEditing_(self, notification)

class TextEntry(BaseTextEntry):
    def make_view(self):
        return MiroTextField.alloc().init()

class NumberEntry(BaseTextEntry):
    def make_view(self):
        return MiroTextField.alloc().init()

    def set_max_length(self, length):
        # TODO
        pass

    def _filter_value(self):
        """Discard any non-numeric characters"""
        digits = ''.join(x for x in self.view.stringValue() if x.isdigit())
        self.view.setStringValue_(digits)

    def on_changed(self, notification):
        # overriding on_changed rather than connecting to it ensures that we
        # filter the value before anything else connected to the signal sees it
        self._filter_value()
        BaseTextEntry.on_changed(self, notification)

    def get_text(self):
        # handles get_text between when text is entered and when on_changed
        # filters it, in case that's possible
        self._filter_value()
        return BaseTextEntry.get_text(self)

class MiroSecureTextField(NSSecureTextField):
    def textDidEndEditing_(self, notification):
        wrappermap.wrapper(self).emit('activate')
        return NSSecureTextField.textDidEndEditing_(self, notification)

class SecureTextEntry(BaseTextEntry):
    def make_view(self):
        return MiroSecureTextField.alloc().init()

class MiroSearchTextField(NSSearchField):
    def init(self):
        self = super(MiroSearchTextField, self).init()
        image = NSImage.alloc().initByReferencingFile_(resources.path('images/search_icon_all.png'))
        self.cell().searchButtonCell().setImage_(image)
        self.cell().searchButtonCell().setAlternateImage_(image)
        return self

    def textDidEndEditing_(self, notification):
        wrappermap.wrapper(self).emit('activate')
        return NSSearchField.textDidEndEditing_(self, notification)

class SearchTextEntry(BaseTextEntry):
    def make_view(self):
        return MiroSearchTextField.alloc().init()

class MultilineTextEntry(Widget):
    def __init__(self, initial_text=None):
        Widget.__init__(self)
        if initial_text is None:
            initial_text = ""
        self.view = NSTextView.alloc().initWithFrame_(NSRect((0,0),(50,50)))
        self.view.setMaxSize_((1.0e7, 1.0e7))
        self.view.setHorizontallyResizable_(NO)
        self.view.setVerticallyResizable_(YES)
        self.notifications = NotificationForwarder.create(self.view)
        self.create_signal('changed')
        self.create_signal('focus-out')
        if initial_text is not None:
            self.set_text(initial_text)
        self.set_size(widgetconst.SIZE_NORMAL)

    def set_size(self, size):
        if size == widgetconst.SIZE_NORMAL:
            font = NSFont.systemFontOfSize_(NSFont.systemFontSize())
        elif size == widgetconst.SIZE_SMALL:
            self.view.cell().setControlSize_(NSSmallControlSize)
        else:
            raise ValueError("Unknown size: %s" % size)
        self.view.setFont_(font)

    def viewport_created(self):
        Widget.viewport_created(self)
        self.notifications.connect(self.on_changed, 'NSTextDidChangeNotification')
        self.notifications.connect(self.on_end_editing,
                'NSControlTextDidEndEditingNotification')
        self.invalidate_size_request()

    def remove_viewport(self):
        Widget.remove_viewport(self)
        self.notifications.disconnect()

    def focus(self):
        if self.view.window() is not None:
            self.view.window().makeFirstResponder_(self.view)

    def set_text(self, text):
        self.view.setString_(text)
        self.invalidate_size_request()

    def get_text(self):
        return self.view.string()

    def on_changed(self, notification):
        self.invalidate_size_request()
        self.emit("changed")

    def on_end_editing(self, notification):
        self.emit("focus-out")

    def calc_size_request(self):
        layout_manager = self.view.layoutManager()
        text_container = self.view.textContainer()
        # The next line is there just to force cocoa to layout the text
        layout_manager.glyphRangeForTextContainer_(text_container)
        rect = layout_manager.usedRectForTextContainer_(text_container)
        return rect.size.width, rect.size.height

    def set_editable(self, editable):
        if editable:
            self.view.setEditable_(YES)
        else:
            self.view.setEditable_(NO)

    
class MiroButton(NSButton):
    
    def initWithSignal_(self, signal):
        self = super(MiroButton, self).init()
        self.signal = signal
        return self
    
    def sendAction_to_(self, action, to):
        # We override the Cocoa machinery here and just send it to our wrapper
        # widget.
        wrappermap.wrapper(self).emit(self.signal)
        return YES

class Checkbox(SizedControl):
    """See https://develop.participatoryculture.org/index.php/WidgetAPI for a description of the API for this class."""
    def __init__(self, text="", bold=False):
        SizedControl.__init__(self)
        self.create_signal('toggled')
        self.view = MiroButton.alloc().initWithSignal_('toggled')
        self.view.setButtonType_(NSSwitchButton)
        self.view.setTitle_(text)
        if bold:
            self.view.setFont_(NSFont.boldSystemFontOfSize_(0))

    def calc_size_request(self):
        size = self.view.cell().cellSize()
        return (size.width, size.height)

    def baseline(self):
        return -self.view.font().descender() + 1

    def get_checked(self):
        return self.view.state() == NSOnState

    def set_checked(self, value):
        if value:
            self.view.setState_(NSOnState)
        else:
            self.view.setState_(NSOffState)

    def enable(self):
        SizedControl.enable(self)
        self.view.setEnabled_(True)

    def disable(self):
        SizedControl.disable(self)
        self.view.setEnabled_(False)

    def get_text_padding(self):
        """
        Returns the amount of space the checkbox takes up before the label.
        """
        # XXX FIXME
        return 18

class Button(SizedControl):
    """See https://develop.participatoryculture.org/index.php/WidgetAPI for a description of the API for this class."""
    def __init__(self, label, style='normal', width=0):
        SizedControl.__init__(self)
        self.color = None
        self.title = label
        self.create_signal('clicked')
        self.view = MiroButton.alloc().initWithSignal_('clicked')
        self.view.setButtonType_(NSMomentaryPushInButton)
        self._set_title()
        self.setup_style(style)
        self.min_width = width

    def set_text(self, label):
        self.title = label
        self._set_title()

    def set_color(self, color):
        self.color = self.make_color(color)
        self._set_title()

    def _set_title(self):
        if self.color is None:
            self.view.setTitle_(self.title)
        else:
            attributes = {
                NSForegroundColorAttributeName: self.color,
                NSFontAttributeName: self.view.font()
            }
            string = NSAttributedString.alloc().initWithString_attributes_(
                    self.title, attributes)
            self.view.setAttributedTitle_(string)

    def setup_style(self, style):
        if style == 'normal':
            self.view.setBezelStyle_(NSRoundedBezelStyle)
            self.pad_height = 0
            self.pad_width = 10
            self.min_width = 112
        elif style == 'smooth':
            self.view.setBezelStyle_(NSRoundRectBezelStyle)
            self.pad_width = 0
            self.pad_height = 4
        self.paragraph_style = NSMutableParagraphStyle.alloc().init()
        self.paragraph_style.setAlignment_(NSCenterTextAlignment)

    def make_default(self):
        self.view.setKeyEquivalent_("\r")

    def calc_size_request(self):
        size = self.view.cell().cellSize()
        width = max(self.min_width, size.width + self.pad_width)
        height = size.height + self.pad_height
        return width, height

    def baseline(self):
        return -self.view.font().descender() + 10 + self.pad_height

    def enable(self):
        SizedControl.enable(self)
        self.view.setEnabled_(True)

    def disable(self):
        SizedControl.disable(self)
        self.view.setEnabled_(False)

class MiroPopupButton(NSPopUpButton):

    def init(self):
        self = super(MiroPopupButton, self).init()
        self.setTarget_(self)
        self.setAction_('handleChange:')
        return self

    def handleChange_(self, sender):
        wrappermap.wrapper(self).emit('changed', self.indexOfSelectedItem())

class OptionMenu(SizedControl):
    def __init__(self, options):
        SizedControl.__init__(self)
        self.create_signal('changed')
        self.view = MiroPopupButton.alloc().init()
        self.options = options
        for option in options:
            self.view.addItemWithTitle_(option)

    def baseline(self):
        if self.view.cell().controlSize() == NSRegularControlSize:
            return -self.view.font().descender() + 6
        else:
            return -self.view.font().descender() + 5

    def calc_size_request(self):
        return self.view.cell().cellSize()

    def set_selected(self, index):
        self.view.selectItemAtIndex_(index)

    def get_selected(self):
        return self.view.indexOfSelectedItem()

    def enable(self):
        SizedControl.enable(self)
        self.view.setEnabled_(True)

    def disable(self):
        SizedControl.disable(self)
        self.view.setEnabled_(False)

    def set_width(self, width):
        # TODO
        pass

class RadioButtonGroup:
    def __init__(self):
        self._buttons = []

    def handle_click(self, widget):
        self.set_selected(widget)

    def add_button(self, button):
        self._buttons.append(button)
        button.connect('clicked', self.handle_click)
        if len(self._buttons) == 1:
            button.view.setState_(NSOnState)
        else:
            button.view.setState_(NSOffState)

    def get_buttons(self):
        return self._buttons

    def get_selected(self):
        for mem in self._buttons:
            if mem.get_selected():
                return mem

    def set_selected(self, button):
        for mem in self._buttons:
            if button is mem:
                mem.view.setState_(NSOnState)
            else:
                mem.view.setState_(NSOffState)

class RadioButton(SizedControl):
    def __init__(self, label, group=None):
        SizedControl.__init__(self)
        self.create_signal('clicked')
        self.view = MiroButton.alloc().initWithSignal_('clicked')
        self.view.setButtonType_(NSRadioButton)
        self.view.setTitle_(label)

        if group is not None:
            self.group = group
        else:
            self.group = RadioButtonGroup() 

        self.group.add_button(self)

    def calc_size_request(self):
        size = self.view.cell().cellSize()
        return (size.width, size.height)

    def baseline(self):
        -self.view.font().descender() + 2

    def get_group(self):
        return self.group

    def get_selected(self):
        return self.view.state() == NSOnState

    def set_selected(self):
        self.group.set_selected(self)

    def enable(self):
        SizedControl.enable(self)
        self.view.setEnabled_(True)

    def disable(self):
        SizedControl.disable(self)
        self.view.setEnabled_(False)


class VideoSearchTextEntry (SearchTextEntry):

    def make_view(self):
        return NSVideoSearchField.alloc().init()

    def selected_engine(self):
        return self.view.currentItem.representedObject().name

    def select_engine(self, engine):
        self.view.selectEngine_(self.view.menuItemForEngine_(engine))

class NSVideoSearchField (MiroSearchTextField):

    def init(self):
        self = super(NSVideoSearchField, self).init()
        self._engineToMenuItem = {}
        self.currentItem = nil
        self.setTarget_(self)
        self.setAction_('search:')
        self.cell().setBezeled_(YES)
        self.cell().setSearchMenuTemplate_(self.makeSearchMenuTemplate())
        self.cell().setSendsWholeSearchString_(YES)
        self.cell().setSendsSearchStringImmediately_(NO)
        self.cell().setScrollable_(YES)
        # handle the user clicking cancel ourselves
        self.cell().cancelButtonCell().setTarget_(self)
        self.cell().cancelButtonCell().setAction_("handleCancel:")
        self.setStringValue_("")
        return self

    # FIXME: ticket #17143 has several improvements for this code

    def handleCancel_(self, sender):
        self.setStringValue_('')
        # emit 'validate' here to clear the search
        wrappermap.wrapper(self).emit('validate')

    def textDidChange_(self, notification):
        # NOTE: we purposely avoid doing anything here.  The Cocoa class calls
        # our action method when the textbox is empty, but this causes issues
        # (#17129, comment 5).
        pass

    def textDidEndEditing_(self, notification):
        # Handle the user stopping typing.
        text_movement = notification.userInfo().get('NSTextMovement')
        if text_movement == NSReturnTextMovement:
            # user hit return, emit 'validate'
            wrappermap.wrapper(self).emit('validate')

        # HACK: not sure exactly why this line has an effect, but it prevents
        # 17195
        self.stringValue()

        # Don't call superclass method.  The cocoa class hides the cancel
        # button if the text is blank, but we want to override that behavior.

    def makeSearchMenuTemplate(self):
        menu = NSMenu.alloc().initWithTitle_("Search Menu")
        for engine in reversed(searchengines.get_search_engines()):
            nsitem = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(engine.title, 'selectEngine:', '')
            nsitem.setTarget_(self)
            nsitem.setImage_(_getEngineIcon(engine))
            nsitem.setRepresentedObject_(engine)
            self._engineToMenuItem[engine.name] = nsitem
            menu.insertItem_atIndex_(nsitem, 0)
        return menu

    def selectEngine_(self, sender):
        if self.currentItem is not nil:
            self.currentItem.setState_(NSOffState)
        self.currentItem = sender
        sender.setState_(NSOnState)
        engine = sender.representedObject()
        self.cell().searchButtonCell().setImage_(_getSearchIcon(engine))

    def search_(self, sender):
        wrappermap.wrapper(self).emit('validate')

    def menuItemForEngine_(self, engine):
        return self._engineToMenuItem[engine]

class VideoSearchFieldCell (NSSearchFieldCell):

    def searchButtonRectForBounds_(self, bounds):
        return NSRect(NSPoint(8.0, 3.0), NSSize(25.0, 16.0))

    def searchTextRectForBounds_(self, bounds):
        textBounds = NSSearchFieldCell.searchTextRectForBounds_(self, bounds)
        cancelButtonBounds = NSSearchFieldCell.cancelButtonRectForBounds_(self, bounds)
        searchButtonBounds = self.searchButtonRectForBounds_(bounds)

        x = searchButtonBounds.origin.x + searchButtonBounds.size.width + 4
        y = textBounds.origin.y
        width = bounds.size.width - x - cancelButtonBounds.size.width
        height = textBounds.size.height

        return ((x, y), (width, height))

NSVideoSearchField.setCellClass_(VideoSearchFieldCell)

def _getEngineIcon(engine):
    engineIconPath = resources.path('images/search_icon_%s.png' % engine.name)
    if app.config.get(prefs.THEME_NAME) and engine.filename:
        if engine.filename.startswith(resources.theme_path(
            app.config.get(prefs.THEME_NAME), 'searchengines')):
                # this search engine came from a theme; look up the icon in the
                # theme directory instead
                engineIconPath = resources.theme_path(
                    app.config.get(prefs.THEME_NAME),
                    'images/search_icon_%s.png' % engine.name)
    if not os.path.exists(engineIconPath):
        return nil
    return NSImage.alloc().initByReferencingFile_(engineIconPath)

searchIcons = dict()
def _getSearchIcon(engine):
    if engine.name not in searchIcons:
        searchIcons[engine.name] = _makeSearchIcon(engine)
    return searchIcons[engine.name]        

def _makeSearchIcon(engine):
    popupRectangle = NSImage.imageNamed_(u'search_popup_triangle')
    popupRectangleSize = popupRectangle.size()

    engineIconPath = resources.path('images/search_icon_%s.png' % engine.name)
    if not os.path.exists(engineIconPath):
        return nil
    engineIcon = NSImage.alloc().initByReferencingFile_(engineIconPath)
    engineIconSize = engineIcon.size()

    searchIconSize = (engineIconSize.width + popupRectangleSize.width + 2, engineIconSize.height)
    searchIcon = NSImage.alloc().initWithSize_(searchIconSize)
    
    searchIcon.lockFocus()
    try:
        engineIcon.compositeToPoint_operation_((0,0), NSCompositeSourceOver)
        popupRectangleX = engineIconSize.width + 2
        popupRectangleY = (engineIconSize.height - popupRectangleSize.height) / 2
        popupRectangle.compositeToPoint_operation_((popupRectangleX, popupRectangleY), NSCompositeSourceOver)
    finally:
        searchIcon.unlockFocus()

    return searchIcon
