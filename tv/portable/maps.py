import tabs
import feed
import folder
import playlist
import guide

# Given an object for which mappableToTab returns true, return a Tab
def mapToTab(obj):
    if isinstance(obj, guide.ChannelGuide):
        # Guides come first and default guide comes before the others.  The rest are currently sorted by URL.
        return tabs.Tab('guidetab', 'go-to-guide', 'default', [1, not obj.getDefault(), obj.getURL()], obj)
    elif isinstance(obj, tabs.StaticTab):
        return tabs.Tab(obj.tabTemplateBase, obj.contentsTemplate, obj.templateState, [obj.order], obj)
    elif isinstance(obj, feed.Feed):
        sortKey = obj.getTitle().lower()
        return tabs.Tab('feedtab', 'channel',  'default', [100, sortKey], obj)
    elif isinstance(obj, folder.ChannelFolder):
        sortKey = obj.getTitle().lower()
        return tabs.Tab('channelfoldertab', 'channel-folder', 'default', [100,sortKey],obj)
    elif isinstance(obj, folder.PlaylistFolder):
        sortKey = obj.getTitle().lower()
        return tabs.Tab('playlistfoldertab','playlist-folder', 'default', [900,sortKey],obj)
    elif isinstance(obj, playlist.SavedPlaylist):
        sortKey = obj.getTitle().lower()
        return tabs.Tab('playlisttab','playlist', 'default',[900,sortKey],obj)
    else:
        raise StandardError
    
