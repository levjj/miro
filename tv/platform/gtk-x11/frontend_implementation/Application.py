import pygtk
pygtk.require('2.0')
import gtk

import frontend



###############################################################################
#### Application object                                                    ####
###############################################################################

class Application:

    def __init__(self):
	print "Application init"

    def Run(self):
	self.onStartup()

        gtk.main()

	self.onShutdown()

    def getBackendDelegate(self):
        return frontend.UIBackendDelegate()

    def onStartup(self):
        # For overriding
        pass

    def onShutdown(self):
        # For overriding
        pass

    # This is called on OS X when we are handling a click on an RSS feed
    # button for Safari. NEEDS: add code here to register as a RSS feed
    # reader on Windows too. Just call this function when we're launched
    # to handle a click on a feed.
    def addAndSelectFeed(self, url):
        # For overriding
        pass

###############################################################################
###############################################################################
