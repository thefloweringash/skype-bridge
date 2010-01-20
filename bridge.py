# Skype to IRC bridge

import sys
import Skype4Py
import irclib
import threading

# stubs

def SendToIrc(skypeChat, user, message):
    ircserver = skype2irc.get(skypeChat.Name)
    if ircserver is not None:
        server = ircservers[ircserver[0]]
        server.connection.privmsg(ircserver[1], "< %s> %s" % (user, message))
    else:
        print "Unroutable message from %s" % skypeChat

def SendToSkype(ircserver, ircchannel, user, message):
    skypechat = irc2skype.get((ircserver, ircchannel))
    if skypechat is not None:
        skype.Chat(skypechat).SendMessage("< %s> %s" % (user, message))
    else:
        print "Unroutable message from %s/%s" % (ircserver, ircchannel)

# skype

def OnAttach(status):
    print 'API attachment status: ' + skype.Convert.AttachmentStatusToText(status)
    if status == Skype4Py.apiAttachAvailable:
        skype.Attach()

def OnMessageStatus(Message, Status):
    if Status == 'RECEIVED': # or Status == 'SENT':
        SendToIrc(Message.Chat, Message.FromDisplayName, Message.Body)
    else:
        print "Ignoring from skype: %s/%s" % (Message.FromDisplayName, Message.Body)

skype = Skype4Py.Skype()
skype.OnAttachmentStatus = OnAttach
skype.OnMessageStatus = OnMessageStatus

print 'Connecting to Skype..'
skype.Attach()

# irc

class DumbIrcClient(irclib.SimpleIRCClient):
    def __init__(self):
        irclib.SimpleIRCClient.__init__(self)

    def on_welcome(self,c,e):
        print "Welcomed!"
        c.join("#flood")
    def on_pubmsg(self,c,e):
        user = e.source()
        user = user[0:user.index('!')]
        SendToSkype(c.server,e.target(), user, e.arguments()[0])

    def run(self):
        self.ircobj.process_forever()

chatmaps = [("#chris.andreae/$c301b64f21991556", ("irc.sitharus.com", "#flood"))]
skype2irc = {}
irc2skype = {}

ircservers = {}

def setupChatmaps(): # WTB: (let (( ... )) )
    for (skype,irc) in chatmaps:
        skype2irc[skype] = irc
        irc2skype[irc] = skype

setupChatmaps()

sitharus = DumbIrcClient()
sitharus.connect("irc.sitharus.com", 6667, "skype")
threading.Thread(None,lambda: sitharus.run()).start()
ircservers["irc.sitharus.com"] = sitharus


print "Unblocked, manual loop"
Cmd = ''
while not Cmd == 'exit':
    Cmd = raw_input('')
